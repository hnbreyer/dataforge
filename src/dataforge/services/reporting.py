from dataforge.engines.analytics import profile
from dataforge.errors import NotFound
from dataforge.models import Report, ReportOutput
from dataforge.schemas import ReportConfig
from dataforge.services.common import page, record
from dataforge.services.datasets import DatasetService, export_rows
from dataforge.services.definitions import DefinitionService


class ReportService:
    def __init__(self, datasets: DatasetService, definitions: DefinitionService):
        self.datasets, self.definitions, self.db = datasets, definitions, datasets.db

    def generate(self, reference: str, config=None, definition: str | None = None) -> dict:
        if config is None and definition is None:
            config = ReportConfig()
        config, definition_id = self.definitions.configuration("report", config, definition)
        with self.db.session() as session:
            dataset = self.datasets.resolve(session, reference)
            columns, rows = self.datasets.load(session, dataset)
            result = profile(columns, rows, config)
            report = Report(
                dataset_id=dataset.id,
                definition_id=definition_id,
                config=config.model_dump(mode="json"),
            )
            report.output = ReportOutput(result=result)
            session.add(report)
            session.flush()
            return {**record(report), "result": result}

    def get(self, report_id: str) -> dict:
        with self.db.session() as session:
            report = session.get(Report, report_id)
            if report is None:
                raise NotFound(f"Report not found: {report_id}")
            return {**record(report), "result": report.output.result}

    def list(self, offset: int = 0, limit: int = 50) -> dict:
        with self.db.session() as session:
            return page(session, Report, offset, limit)

    def export(self, report_id: str, format: str = "json", spreadsheet_safe: bool = False) -> bytes:
        import json

        report = self.get(report_id)
        if format == "json":
            return (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        groups = report["result"]["groups"]
        columns = (
            list(groups[0])
            if groups
            else report["config"]["group_by"] + [m["name"] for m in report["config"]["metrics"]]
        )
        return export_rows(columns, groups, format, spreadsheet_safe)
