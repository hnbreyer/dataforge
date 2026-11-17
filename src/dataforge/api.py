"""Versioned thin HTTP adapter and application factory."""

from contextlib import asynccontextmanager
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from dataforge.config import Settings
from dataforge.errors import ForgeError
from dataforge.schemas import (
    DatasetResponse,
    DefinitionCreate,
    DefinitionResponse,
    JobResponse,
    Page,
    PipelineRequest,
    PreviewResponse,
    ReportRequest,
    ReportResponse,
    ValidationRequest,
    ValidationResponse,
)
from dataforge.workspace import Workspace

Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=200)]
Format = Literal["csv", "json"]
Kind = Literal["validation", "pipeline", "report"]


def current_workspace(request: Request) -> Workspace:
    return request.app.state.workspace


Work = Annotated[Workspace, Depends(current_workspace)]


def download(data: bytes, filename: str, format: str) -> Response:
    return Response(
        data,
        media_type="text/csv" if format == "csv" else "application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}.{format}"'},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        workspace = Workspace(settings)
        workspace.initialize()
        app.state.workspace = workspace
        try:
            yield
        finally:
            workspace.close()

    app = FastAPI(
        title="DataForge",
        docs_url=None,
        redoc_url=None,
        version="0.1.0",
        description="Local-first immutable datasets, deterministic validation, pipelines, and reports. Jobs execute synchronously.",
        lifespan=lifespan,
    )
    from dataforge.web.middleware import BodyLimitMiddleware

    app.add_middleware(BodyLimitMiddleware, max_file_bytes=settings.max_file_bytes)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def local_browser_protection(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            cross_site = request.headers.get("sec-fetch-site") == "cross-site"
            if cross_site or origin is not None and urlsplit(origin).netloc != request.url.netloc:
                return JSONResponse(
                    {"detail": "Cross-origin writes are not allowed"}, status_code=403
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
        )
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.exception_handler(ForgeError)
    async def business_error(request: Request, exc: ForgeError):
        if not request.url.path.startswith("/api/"):
            from dataforge.web.routes import templates

            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={"message": str(exc), "status": exc.status_code},
                status_code=exc.status_code,
            )
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        return JSONResponse(
            {"detail": "Database operation failed; check workspace permissions and migrations"},
            status_code=503,
        )

    api = APIRouter(prefix="/api/v1")

    @api.get("/health", tags=["workspace"])
    def health(workspace: Work) -> dict:
        return {"status": "ok", "summary": workspace.summary()}

    @api.get("/datasets", response_model=Page, tags=["datasets"])
    def datasets(workspace: Work, search: str = "", offset: Offset = 0, limit: Limit = 50):
        return workspace.datasets.list(search, offset, limit)

    @api.post("/imports", response_model=DatasetResponse, status_code=201, tags=["datasets"])
    def import_file(
        workspace: Work,
        name: Annotated[str, Form(min_length=1, max_length=120)],
        file: Annotated[UploadFile, File()],
    ):
        data = file.file.read(settings.max_file_bytes + 1)
        return workspace.datasets.import_bytes(data, file.filename or "upload", name)

    @api.get("/imports", response_model=Page, tags=["datasets"])
    def imports(workspace: Work, offset: Offset = 0, limit: Limit = 50):
        return workspace.imports(offset, limit)

    @api.get("/datasets/{reference}", response_model=DatasetResponse, tags=["datasets"])
    def dataset(reference: str, workspace: Work):
        return workspace.datasets.get(reference)

    @api.get("/datasets/{reference}/preview", response_model=PreviewResponse, tags=["datasets"])
    def preview(reference: str, workspace: Work, offset: Offset = 0, limit: Limit = 20):
        return workspace.datasets.preview(reference, offset, limit)

    @api.get("/datasets/{reference}/export", tags=["exports"], response_class=Response)
    def export(
        reference: str, workspace: Work, format: Format = "csv", spreadsheet_safe: bool = False
    ):
        dataset = workspace.datasets.get(reference)
        return download(
            workspace.datasets.export(reference, format, spreadsheet_safe), dataset["id"], format
        )

    @api.get("/datasets/{reference}/source", tags=["exports"], response_class=Response)
    def source(reference: str, workspace: Work):
        dataset = workspace.datasets.get(reference)
        return Response(
            workspace.datasets.source(reference),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{dataset["id"]}.bin"'},
        )

    @api.delete("/datasets/{reference}", tags=["datasets"])
    def delete_dataset(reference: str, workspace: Work, confirm: bool = False) -> dict:
        return workspace.datasets.delete(reference, confirm)

    @api.post(
        "/datasets/{reference}/validations",
        response_model=ValidationResponse,
        response_model_exclude_none=True,
        status_code=201,
        tags=["validation"],
    )
    def validate(reference: str, body: ValidationRequest, workspace: Work):
        return workspace.validation.run(reference, body.config, body.definition)

    @api.get("/validations", response_model=Page, tags=["validation"])
    def validations(workspace: Work, offset: Offset = 0, limit: Limit = 50):
        return workspace.validation.list(offset, limit)

    @api.get("/validations/{run_id}", response_model=ValidationResponse, tags=["validation"])
    def validation(run_id: str, workspace: Work, offset: Offset = 0, limit: Limit = 50):
        return workspace.validation.get(run_id, offset, limit)

    @api.post("/pipelines/run", response_model=JobResponse, status_code=201, tags=["pipelines"])
    def pipeline(body: PipelineRequest, workspace: Work):
        return workspace.pipelines.run(body.dataset, body.output_name, body.config, body.definition)

    @api.get("/jobs", response_model=Page, tags=["pipelines"])
    def jobs(workspace: Work, offset: Offset = 0, limit: Limit = 50):
        return workspace.pipelines.list(offset, limit)

    @api.get("/jobs/{job_id}", response_model=JobResponse, tags=["pipelines"])
    def job(job_id: str, workspace: Work):
        return workspace.pipelines.get(job_id)

    @api.post("/jobs/{job_id}/recover", response_model=JobResponse, tags=["pipelines"])
    def recover_job(job_id: str, workspace: Work, confirm: bool = False):
        return workspace.pipelines.recover(job_id, confirm)

    @api.post(
        "/datasets/{reference}/reports",
        response_model=ReportResponse,
        status_code=201,
        tags=["reports"],
    )
    def generate_report(reference: str, workspace: Work, body: ReportRequest | None = None):
        return workspace.reports.generate(
            reference, body.config if body else None, body.definition if body else None
        )

    @api.get("/reports", response_model=Page, tags=["reports"])
    def reports(workspace: Work, offset: Offset = 0, limit: Limit = 50):
        return workspace.reports.list(offset, limit)

    @api.get("/reports/{report_id}", response_model=ReportResponse, tags=["reports"])
    def report(report_id: str, workspace: Work):
        return workspace.reports.get(report_id)

    @api.get("/reports/{report_id}/export", tags=["exports"], response_class=Response)
    def report_export(
        report_id: str, workspace: Work, format: Format = "json", spreadsheet_safe: bool = False
    ):
        return download(
            workspace.reports.export(report_id, format, spreadsheet_safe), report_id, format
        )

    @api.post(
        "/definitions/{kind}",
        response_model=DefinitionResponse,
        status_code=201,
        tags=["definitions"],
    )
    def save_definition(kind: Kind, body: DefinitionCreate, workspace: Work):
        return workspace.definitions.save(kind, body.name, body.config)

    @api.get("/definitions/{kind}", response_model=Page, tags=["definitions"])
    def definitions(kind: Kind, workspace: Work, offset: Offset = 0, limit: Limit = 50):
        return workspace.definitions.list(kind, offset, limit)

    @api.get(
        "/definitions/{kind}/{reference}", response_model=DefinitionResponse, tags=["definitions"]
    )
    def definition(kind: Kind, reference: str, workspace: Work):
        return workspace.definitions.get(kind, reference)

    @api.delete("/history/{kind}/{reference}", tags=["workspace"])
    def delete_history(
        kind: Literal["validation", "job", "report", "import"],
        reference: str,
        workspace: Work,
        confirm: bool = False,
    ) -> dict:
        return workspace.delete_history(kind, reference, confirm)

    app.include_router(api)
    from fastapi.staticfiles import StaticFiles

    from dataforge.web.routes import router, static_path

    app.mount("/static", StaticFiles(directory=static_path), name="static")
    app.include_router(router)
    return app
