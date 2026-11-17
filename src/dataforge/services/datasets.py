import csv
import io
import json
from contextlib import suppress
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dataforge.db import Database
from dataforge.engines.parsing import column_metadata, parse_data
from dataforge.errors import Conflict, ForgeError, InputError, NotFound
from dataforge.models import Artifact, Column, Dataset, ImportRecord, Job, Report, ValidationRun
from dataforge.schemas import Name
from dataforge.services.common import page, record
from dataforge.storage import Storage, checksum


def valid_name(name: str) -> str:
    try:
        return TypeAdapter(Name).validate_python(name)
    except ValidationError as exc:
        raise InputError("Name must be a nonblank string of at most 120 characters") from exc


def export_rows(
    columns: list[str], rows: list[dict], format: str, spreadsheet_safe: bool = False
) -> bytes:
    if format == "json":
        return (json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
            "utf-8"
        )
    if format != "csv":
        raise InputError("Export format must be csv or json")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")

    def cell(value):
        if (
            spreadsheet_safe
            and isinstance(value, str)
            and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
        ):
            return "'" + value
        return value

    writer.writerow([cell(c) for c in columns])
    writer.writerows([cell(row[c]) for c in columns] for row in rows)
    return output.getvalue().encode("utf-8")


class DatasetService:
    def __init__(self, db: Database, storage: Storage):
        self.db, self.storage = db, storage

    def resolve(self, session: Session, reference: str) -> Dataset:
        dataset = session.get(Dataset, reference)
        if dataset is None:
            dataset = session.scalar(select(Dataset).where(Dataset.name == reference))
        if dataset is None:
            raise NotFound(f"Dataset not found: {reference}")
        return dataset

    def describe(self, dataset: Dataset) -> dict:
        result = record(dataset)
        result["columns"] = [record(c, {"id", "dataset_id"}) for c in dataset.columns]
        return result

    def insert(
        self,
        session: Session,
        name: str,
        filename: str,
        columns: list[str],
        rows: list[dict],
        artifacts: list[dict],
        parent_id: str | None = None,
    ) -> Dataset:
        name = valid_name(name)
        if session.scalar(select(Dataset.id).where(Dataset.name == name)):
            raise Conflict(f"Dataset name already exists: {name}")
        canonical = next(a for a in artifacts if a["kind"] == "processed")
        source = next((a for a in artifacts if a["kind"] == "source"), canonical)
        dataset = Dataset(
            name=name,
            source_filename=filename,
            row_count=len(rows),
            checksum=source["checksum"],
            parent_id=parent_id,
        )
        dataset.columns = [Column(**c) for c in column_metadata(columns, rows)]
        dataset.artifacts = [Artifact(**artifact) for artifact in artifacts]
        session.add(dataset)
        session.flush()
        return dataset

    def import_file(self, path: Path, name: str) -> dict:
        try:
            with path.open("rb") as handle:
                data = handle.read(self.db.settings.max_file_bytes + 1)
        except OSError as exc:
            self._failed_import(path.name, name, "Input file is missing or unreadable", None)
            raise InputError("Input file is missing or unreadable") from exc
        return self.import_bytes(data, path.name, name)

    def _failed_import(self, filename: str, name: str, error: str, digest: str | None):
        with self.db.session() as session:
            session.add(
                ImportRecord(
                    filename=filename,
                    requested_name=str(name),
                    status="failed",
                    error=error[:4000],
                    checksum=digest,
                )
            )

    def import_bytes(self, data: bytes, filename: str, name: str) -> dict:
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1][:255]
        artifacts = []
        digest = checksum(data)
        try:
            name = valid_name(name)
            columns, rows = parse_data(data, filename, self.db.settings)
            with self.db.session() as session:
                # Fail duplicate names before writing artifacts.
                if session.scalar(select(Dataset.id).where(Dataset.name == name)):
                    raise Conflict(f"Dataset name already exists: {name}")
                artifacts.append(self.storage.write("source", data))
                artifacts.append(self.storage.write_rows(rows))
                dataset = self.insert(session, name, filename, columns, rows, artifacts)
                session.add(
                    ImportRecord(
                        dataset_id=dataset.id,
                        filename=filename,
                        requested_name=name,
                        status="succeeded",
                        checksum=digest,
                    )
                )
                result = self.describe(dataset)
            return result
        except Exception as exc:
            self.storage.discard(artifacts)
            message = str(exc) if isinstance(exc, ForgeError) else "Import could not be committed"
            self._failed_import(filename, name, message, digest)
            if isinstance(exc, IntegrityError):
                raise Conflict(
                    "Dataset name already exists or a concurrent import conflicted"
                ) from exc
            if isinstance(exc, OSError):
                raise InputError("Unable to store imported data") from exc
            raise

    def list(self, search: str = "", offset: int = 0, limit: int = 50) -> dict:
        with self.db.session() as session:
            filters = (Dataset.name.contains(search, autoescape=True),) if search else ()
            return page(session, Dataset, offset, limit, filters)

    def get(self, reference: str) -> dict:
        with self.db.session() as session:
            return self.describe(self.resolve(session, reference))

    def load(self, session: Session, dataset: Dataset) -> tuple[list[str], list[dict]]:
        artifact = next(a for a in dataset.artifacts if a.kind == "processed")
        return [c.name for c in dataset.columns], self.storage.rows(artifact)

    def preview(self, reference: str, offset: int = 0, limit: int = 20) -> dict:
        if offset < 0 or not 1 <= limit <= 200:
            raise InputError("Preview requires offset >= 0 and limit between 1 and 200")
        with self.db.session() as session:
            dataset = self.resolve(session, reference)
            columns, rows = self.load(session, dataset)
            return {
                "dataset_id": dataset.id,
                "columns": columns,
                "items": rows[offset : offset + limit],
                "total": dataset.row_count,
                "offset": offset,
                "limit": limit,
            }

    def export(self, reference: str, format: str = "csv", spreadsheet_safe: bool = False) -> bytes:
        with self.db.session() as session:
            dataset = self.resolve(session, reference)
            columns, rows = self.load(session, dataset)
            return export_rows(columns, rows, format, spreadsheet_safe)

    def source(self, reference: str) -> bytes:
        with self.db.session() as session:
            dataset = self.resolve(session, reference)
            artifact = next((a for a in dataset.artifacts if a.kind == "source"), None)
            if artifact is None:
                raise NotFound(
                    "Transformed datasets have no imported source file; follow parent_id"
                )
            return self.storage.read(artifact)

    def delete(self, reference: str, confirmed: bool = False) -> dict:
        if not confirmed:
            raise Conflict("Deletion requires explicit confirmation")
        paths = []
        try:
            with self.db.session() as session:
                dataset = self.resolve(session, reference)
                dependencies = [
                    (Dataset, Dataset.parent_id == dataset.id),
                    (ValidationRun, ValidationRun.dataset_id == dataset.id),
                    (Job, or_(Job.input_id == dataset.id, Job.output_id == dataset.id)),
                    (Report, Report.dataset_id == dataset.id),
                ]
                for model, condition in dependencies:
                    if session.scalar(select(func.count()).select_from(model).where(condition)):
                        raise Conflict(
                            f"Dataset has dependent {model.__tablename__}; remove that history or derived data first"
                        )
                paths = [{"path": a.path} for a in dataset.artifacts]
                result = {"deleted": dataset.id}
                session.delete(dataset)
        except IntegrityError as exc:
            raise Conflict("Dataset has dependencies and cannot be deleted") from exc
        # A crash here can leave unreferenced files, never metadata pointing at deleted files.
        for item in paths:
            with suppress(OSError):
                self.storage.discard([item])
        return result
