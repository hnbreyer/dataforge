from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from dataforge.engines.transformation import transform
from dataforge.engines.validation import validate_rows
from dataforge.errors import Conflict, ForgeError, InputError, NotFound
from dataforge.models import Job, ValidationIssue, ValidationRun, now
from dataforge.services.common import page, record
from dataforge.services.datasets import DatasetService, valid_name
from dataforge.services.definitions import DefinitionService


class ValidationService:
    def __init__(self, datasets: DatasetService, definitions: DefinitionService):
        self.datasets, self.definitions, self.db = datasets, definitions, datasets.db

    def run(self, reference: str, config=None, definition: str | None = None) -> dict:
        config, definition_id = self.definitions.configuration("validation", config, definition)
        with self.db.session() as session:
            dataset = self.datasets.resolve(session, reference)
            columns, rows = self.datasets.load(session, dataset)
            issues = validate_rows(columns, rows, config)
            run = ValidationRun(
                dataset_id=dataset.id,
                definition_id=definition_id,
                config=config.model_dump(mode="json"),
                passed=not any(i["severity"] == "error" for i in issues),
                issue_count=len(issues),
            )
            run.issues = [ValidationIssue(**issue) for issue in issues]
            session.add(run)
            session.flush()
            return record(run)

    def get(self, run_id: str, offset: int = 0, limit: int = 50) -> dict:
        with self.db.session() as session:
            run = session.get(ValidationRun, run_id)
            if run is None:
                raise NotFound(f"Validation run not found: {run_id}")
            result = record(run)
            result["issues"] = page(
                session,
                ValidationIssue,
                offset,
                limit,
                (ValidationIssue.run_id == run_id,),
                ascending=True,
            )
            return result

    def list(self, offset: int = 0, limit: int = 50) -> dict:
        with self.db.session() as session:
            return page(session, ValidationRun, offset, limit)


class PipelineService:
    def __init__(self, datasets: DatasetService, definitions: DefinitionService):
        self.datasets, self.definitions, self.db = datasets, definitions, datasets.db

    def run(
        self, reference: str, output_name: str, config=None, definition: str | None = None
    ) -> dict:
        config, definition_id = self.definitions.configuration("pipeline", config, definition)
        output_name = valid_name(output_name)
        with self.db.session() as session:
            dataset = self.datasets.resolve(session, reference)
            job = Job(
                input_id=dataset.id,
                definition_id=definition_id,
                config=config.model_dump(mode="json"),
                status="running",
            )
            session.add(job)
            session.flush()
            job_id, dataset_id = job.id, dataset.id
        artifacts = []
        try:
            with self.db.session() as session:
                dataset = self.datasets.resolve(session, dataset_id)
                columns, rows = self.datasets.load(session, dataset)
            columns, rows = transform(columns, rows, config, self.db.settings)
            artifacts.append(self.datasets.storage.write_rows(rows))
            with self.db.session() as session:
                # Claim the final commit with a conditional write. Recovery can
                # revoke a running job, but cannot race a committed output.
                claimed = session.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "running")
                    .values(status="running")
                )
                if claimed.rowcount != 1:
                    raise Conflict("Job was recovered or cancelled before output commit")
                output = self.datasets.insert(
                    session,
                    output_name,
                    "pipeline-output.jsonl",
                    columns,
                    rows,
                    artifacts,
                    parent_id=dataset_id,
                )
                job = session.get(Job, job_id)
                job.status, job.output_id, job.finished_at = "succeeded", output.id, now()
                result = record(job)
            return result
        except Exception as exc:
            self.datasets.storage.discard(artifacts)
            message = str(exc) if isinstance(exc, ForgeError) else "Pipeline could not be committed"
            with self.db.session() as session:
                job = session.get(Job, job_id)
                if job.status == "running":
                    job.status, job.error, job.finished_at = "failed", message[:4000], now()
            if isinstance(exc, IntegrityError):
                raise Conflict(f"Pipeline job {job_id} failed: conflicting output name") from exc
            if isinstance(exc, (ForgeError, OSError)):
                raise InputError(f"Pipeline job {job_id} failed: {message}") from exc
            raise

    def get(self, job_id: str) -> dict:
        with self.db.session() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise NotFound(f"Job not found: {job_id}")
            return record(job)

    def list(self, offset: int = 0, limit: int = 50) -> dict:
        with self.db.session() as session:
            return page(session, Job, offset, limit)

    def recover(self, job_id: str, confirmed: bool = False) -> dict:
        """Explicitly mark interrupted work failed and revoke its commit permission."""
        if not confirmed:
            raise Conflict("Recovering a job requires explicit confirmation")
        with self.db.session() as session:
            result = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(
                    status="failed",
                    error="Interrupted job explicitly recovered by user",
                    finished_at=now(),
                )
            )
            if result.rowcount != 1:
                if session.get(Job, job_id) is None:
                    raise NotFound(f"Job not found: {job_id}")
                raise Conflict("Only running jobs can be recovered")
            return record(session.get(Job, job_id))
