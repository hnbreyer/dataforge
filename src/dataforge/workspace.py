"""Composition root shared by all three interfaces."""

from sqlalchemy import func, select

from dataforge.config import Settings
from dataforge.db import Database
from dataforge.errors import Conflict, InputError, NotFound
from dataforge.models import Dataset, ImportRecord, Job, Report, ValidationRun
from dataforge.services.common import page
from dataforge.services.datasets import DatasetService
from dataforge.services.definitions import DefinitionService
from dataforge.services.processing import PipelineService, ValidationService
from dataforge.services.reporting import ReportService
from dataforge.storage import Storage


class Workspace:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.db = Database(self.settings)
        self.storage = Storage(self.settings)
        self.datasets = DatasetService(self.db, self.storage)
        self.definitions = DefinitionService(self.db)
        self.validation = ValidationService(self.datasets, self.definitions)
        self.pipelines = PipelineService(self.datasets, self.definitions)
        self.reports = ReportService(self.datasets, self.definitions)

    def initialize(self):
        self.db.migrate()

    def close(self):
        self.db.close()

    def summary(self) -> dict:
        with self.db.session() as session:

            def count(model, *conditions):
                return session.scalar(select(func.count()).select_from(model).where(*conditions))

            return {
                "datasets": count(Dataset),
                "rows": session.scalar(select(func.coalesce(func.sum(Dataset.row_count), 0))),
                "validations": count(ValidationRun),
                "validation_failures": count(ValidationRun, ValidationRun.passed.is_(False)),
                "jobs": count(Job),
                "failed_jobs": count(Job, Job.status == "failed"),
                "reports": count(Report),
            }

    def imports(self, offset: int = 0, limit: int = 50) -> dict:
        with self.db.session() as session:
            return page(session, ImportRecord, offset, limit)

    def delete_history(self, kind: str, reference: str, confirmed: bool = False) -> dict:
        if not confirmed:
            raise Conflict("History deletion requires explicit confirmation")
        model = {
            "validation": ValidationRun,
            "job": Job,
            "report": Report,
            "import": ImportRecord,
        }.get(kind)
        if model is None:
            raise InputError("History kind must be validation, job, report, or import")
        with self.db.session() as session:
            item = session.get(model, reference)
            if item is None:
                raise NotFound(f"{kind} history not found: {reference}")
            if isinstance(item, Job) and item.status == "running":
                raise Conflict("A running job cannot be deleted")
            session.delete(item)
        return {"deleted": reference}
