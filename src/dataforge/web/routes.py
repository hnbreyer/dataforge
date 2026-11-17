import json
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from dataforge.api import Limit, Offset, Work
from dataforge.errors import InputError

static_path = Path(__file__).parent / "static"
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter(include_in_schema=False)


def render(request: Request, name: str, **context):
    return templates.TemplateResponse(request=request, name=name, context=context)


def redirect(path: str):
    return RedirectResponse(path, status_code=303)


def parse_form_config(config: str, definition: str):
    if definition:
        if config.strip():
            raise InputError("Choose a saved definition or enter JSON, not both")
        return {"definition": definition}
    if len(config) > 1_000_000:
        raise InputError("Configuration exceeds 1 MB limit")
    try:
        value = json.loads(config or "{}")
    except (ValueError, RecursionError) as exc:
        raise InputError("Configuration must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise InputError("Configuration must be a JSON object")
    return {"config": value}


def pagination(path: str, result: dict, search: str = "") -> dict:
    offset, limit, total = result["offset"], result["limit"], result["total"]

    def link(position):
        return path + "?" + urlencode({"offset": position, "limit": limit, "search": search})

    return {
        "previous": link(max(0, offset - limit)) if offset else None,
        "next": link(offset + limit) if offset + limit < total else None,
    }


@router.get("/")
def overview(request: Request, workspace: Work):
    return render(
        request,
        "overview.html",
        summary=workspace.summary(),
        recent=workspace.datasets.list(limit=5),
        jobs=workspace.pipelines.list(limit=5),
    )


@router.get("/datasets")
def datasets(
    request: Request, workspace: Work, search: str = "", offset: Offset = 0, limit: Limit = 25
):
    result = workspace.datasets.list(search, offset, limit)
    return render(
        request,
        "datasets.html",
        page=result,
        search=search,
        pager=pagination("/datasets", result, search),
    )


@router.get("/import")
def import_page(request: Request):
    return render(request, "import.html")


@router.post("/import")
def import_file(
    workspace: Work,
    name: Annotated[str, Form(min_length=1, max_length=120)],
    file: Annotated[UploadFile, File()],
):
    result = workspace.datasets.import_bytes(
        file.file.read(workspace.settings.max_file_bytes + 1), file.filename or "upload", name
    )
    return redirect(f"/datasets/{result['id']}")


@router.get("/datasets/{reference}")
def dataset(
    request: Request, reference: str, workspace: Work, offset: Offset = 0, limit: Limit = 20
):
    dataset = workspace.datasets.get(reference)
    preview = workspace.datasets.preview(reference, offset, limit)
    return render(
        request,
        "dataset.html",
        dataset=dataset,
        preview=preview,
        definitions=workspace.definitions.list("validation", limit=200)["items"],
        pager=pagination(f"/datasets/{dataset['id']}", preview),
    )


@router.post("/datasets/{reference}/validate")
def validate(
    reference: str,
    workspace: Work,
    config: Annotated[str, Form()] = "",
    definition: Annotated[str, Form()] = "",
):
    result = workspace.validation.run(reference, **parse_form_config(config, definition))
    return redirect(f"/validations/{result['id']}")


@router.post("/datasets/{reference}/delete")
def delete_dataset(reference: str, workspace: Work, confirm: Annotated[bool, Form()] = False):
    workspace.datasets.delete(reference, confirm)
    return redirect("/datasets")


@router.get("/validations")
def validations(request: Request, workspace: Work, offset: Offset = 0, limit: Limit = 25):
    result = workspace.validation.list(offset, limit)
    return render(
        request,
        "history.html",
        title="Validation",
        subtitle="Read-only checks, with every issue linked to its record.",
        kind="validation",
        page=result,
        pager=pagination("/validations", result),
    )


@router.get("/validations/{run_id}")
def validation(
    request: Request, run_id: str, workspace: Work, offset: Offset = 0, limit: Limit = 50
):
    result = workspace.validation.get(run_id, offset, limit)
    return render(
        request,
        "validation.html",
        run=result,
        pager=pagination(f"/validations/{run_id}", result["issues"]),
    )


@router.get("/pipelines")
def pipelines(request: Request, workspace: Work, offset: Offset = 0, limit: Limit = 25):
    result = workspace.pipelines.list(offset, limit)
    return render(
        request,
        "pipelines.html",
        page=result,
        datasets=workspace.datasets.list(limit=200)["items"],
        definitions=workspace.definitions.list("pipeline", limit=200)["items"],
        pager=pagination("/pipelines", result),
    )


@router.post("/pipelines")
def execute_pipeline(
    workspace: Work,
    dataset: Annotated[str, Form()],
    output_name: Annotated[str, Form()],
    config: Annotated[str, Form()] = "",
    definition: Annotated[str, Form()] = "",
):
    result = workspace.pipelines.run(dataset, output_name, **parse_form_config(config, definition))
    return redirect(f"/jobs/{result['id']}")


@router.get("/jobs/{job_id}")
def job(request: Request, job_id: str, workspace: Work):
    return render(request, "job.html", job=workspace.pipelines.get(job_id))


@router.get("/reports")
def reports(request: Request, workspace: Work, offset: Offset = 0, limit: Limit = 25):
    result = workspace.reports.list(offset, limit)
    return render(
        request,
        "reports.html",
        page=result,
        datasets=workspace.datasets.list(limit=200)["items"],
        definitions=workspace.definitions.list("report", limit=200)["items"],
        pager=pagination("/reports", result),
    )


@router.post("/reports")
def generate_report(
    workspace: Work,
    dataset: Annotated[str, Form()],
    config: Annotated[str, Form()] = "",
    definition: Annotated[str, Form()] = "",
):
    result = workspace.reports.generate(dataset, **parse_form_config(config, definition))
    return redirect(f"/reports/{result['id']}")


@router.get("/reports/{report_id}")
def report(request: Request, report_id: str, workspace: Work):
    return render(request, "report.html", report=workspace.reports.get(report_id))


@router.get("/imports")
def imports(request: Request, workspace: Work, offset: Offset = 0, limit: Limit = 25):
    result = workspace.imports(offset, limit)
    return render(request, "imports.html", page=result, pager=pagination("/imports", result))


@router.get("/definitions")
def definitions(
    request: Request,
    workspace: Work,
    kind: str = "validation",
    offset: Offset = 0,
    limit: Limit = 25,
):
    result = workspace.definitions.list(kind, offset, limit)
    pager = pagination("/definitions", result)
    pager = {
        key: value + "&" + urlencode({"kind": kind}) if value else None
        for key, value in pager.items()
    }
    return render(request, "definitions.html", kind=kind, page=result, pager=pager)


@router.post("/definitions")
def save_definition(
    workspace: Work,
    kind: Annotated[str, Form()],
    name: Annotated[str, Form()],
    config: Annotated[str, Form()],
):
    workspace.definitions.save(kind, name, parse_form_config(config, "")["config"])
    return redirect("/definitions?" + urlencode({"kind": kind}))


@router.get("/docs")
def api_reference(request: Request):
    """Offline OpenAPI reference; no external JavaScript, fonts, or stylesheets."""
    return render(request, "api_reference.html", spec=request.app.openapi())
