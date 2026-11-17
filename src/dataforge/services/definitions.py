from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from dataforge.db import Database
from dataforge.errors import Conflict, InputError, NotFound
from dataforge.models import Definition
from dataforge.schemas import PipelineConfig, ReportConfig, RuleSet
from dataforge.services.common import page, parse_config, record
from dataforge.services.datasets import valid_name

SCHEMAS = {"validation": RuleSet, "pipeline": PipelineConfig, "report": ReportConfig}


class DefinitionService:
    def __init__(self, db: Database):
        self.db = db

    def check_kind(self, kind: str):
        if kind not in SCHEMAS:
            raise InputError("Definition kind must be validation, pipeline, or report")

    def save(self, kind: str, name: str, config: dict) -> dict:
        self.check_kind(kind)
        validated = parse_config(SCHEMAS[kind], config)
        try:
            with self.db.session() as session:
                definition = Definition(
                    kind=kind, name=valid_name(name), config=validated.model_dump(mode="json")
                )
                session.add(definition)
                session.flush()
                return record(definition)
        except IntegrityError as exc:
            raise Conflict(
                f"A {kind} definition named {name} already exists; use a new name to version it"
            ) from exc

    def get(self, kind: str, reference: str) -> dict:
        self.check_kind(kind)
        with self.db.session() as session:
            definition = session.get(Definition, reference)
            if definition is None or definition.kind != kind:
                definition = session.scalar(
                    select(Definition).where(Definition.kind == kind, Definition.name == reference)
                )
            if definition is None:
                raise NotFound(f"{kind} definition not found: {reference}")
            return record(definition)

    def list(self, kind: str, offset: int = 0, limit: int = 50) -> dict:
        self.check_kind(kind)
        with self.db.session() as session:
            return page(session, Definition, offset, limit, (Definition.kind == kind,))

    def configuration(self, kind: str, config, reference: str | None):
        if (config is None) == (reference is None):
            raise InputError("Provide exactly one configuration or saved definition")
        if reference is not None:
            definition = self.get(kind, reference)
            return parse_config(SCHEMAS[kind], definition["config"]), definition["id"]
        return parse_config(SCHEMAS[kind], config), None
