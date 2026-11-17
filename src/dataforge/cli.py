"""Typer adapter: no processing logic and no web-server dependency."""

import json
import os
import tempfile
from functools import wraps
from pathlib import Path

import typer
from sqlalchemy.exc import SQLAlchemyError

from dataforge.config import Settings
from dataforge.errors import ForgeError, InputError
from dataforge.workspace import Workspace

app = typer.Typer(
    help="Local data processing and analytics. Use --home to isolate a workspace.",
    no_args_is_help=True,
)
dataset_app = typer.Typer(
    help="Import, inspect, export, and delete immutable datasets.", no_args_is_help=True
)
validation_app = typer.Typer(
    help="Run read-only validation and inspect issues.", no_args_is_help=True
)
pipeline_app = typer.Typer(
    help="Execute pipelines atomically and browse jobs.", no_args_is_help=True
)
report_app = typer.Typer(
    help="Generate, inspect, and export reproducible reports.", no_args_is_help=True
)
definition_app = typer.Typer(
    help="Save immutable, reusable validation/pipeline/report configurations.", no_args_is_help=True
)
history_app = typer.Typer(
    help="Inspect imports and remove processing history explicitly.", no_args_is_help=True
)
app.add_typer(dataset_app, name="dataset")
app.add_typer(validation_app, name="validate")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(report_app, name="report")
app.add_typer(definition_app, name="definition")
app.add_typer(history_app, name="history")


def handled(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ForgeError, OSError, ValueError) as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc
        except SQLAlchemyError as exc:
            typer.echo(
                "Error: Database operation failed. Run 'dataforge init' and check workspace permissions.",
                err=True,
            )
            raise typer.Exit(1) from exc

    return wrapper


@app.callback()
def options(
    ctx: typer.Context,
    home: Path | None = typer.Option(
        None, help="Workspace data directory; defaults to DATAFORGE_HOME or .dataforge."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit compact machine-readable JSON."),
):
    settings = Settings(home=home) if home is not None else Settings()
    workspace = Workspace(settings)
    ctx.obj = {"workspace": workspace, "json": json_output}
    ctx.call_on_close(workspace.close)


def work(ctx: typer.Context) -> Workspace:
    return ctx.obj["workspace"]


def emit(ctx: typer.Context, result):
    typer.echo(json.dumps(result, ensure_ascii=False, indent=None if ctx.obj["json"] else 2))


def configuration(path: Path) -> dict:
    if path.stat().st_size > 1_000_000:
        raise InputError("Configuration exceeds 1 MB limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InputError(f"Invalid UTF-8 JSON configuration: {exc}") from exc
    if not isinstance(value, dict):
        raise InputError("Configuration must be a JSON object")
    return value


def config_or_definition(path: Path | None, definition: str | None) -> dict:
    if path is not None and definition is not None:
        raise InputError("Provide a configuration file or --definition, not both")
    return {"config": configuration(path) if path is not None else None, "definition": definition}


def save_export(output: Path | None, data: bytes):
    if output is None:
        typer.echo(data.decode("utf-8"), nl=False)
        return
    output = output.expanduser().resolve()
    if output.exists():
        raise InputError("Export target already exists; choose a new path")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent, prefix=".dataforge-export-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link creation is atomic and cannot overwrite a source or existing export.
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    typer.echo(f"Exported to {output}", err=True)


@app.command()
@handled
def init(ctx: typer.Context):
    """Create the workspace and apply all pending Alembic migrations."""
    work(ctx).initialize()
    emit(ctx, {"initialized": str(work(ctx).settings.home)})


@app.command()
@handled
def status(ctx: typer.Context):
    """Summarize datasets and processing history."""
    emit(ctx, work(ctx).summary())


@dataset_app.command("import")
@handled
def dataset_import(ctx: typer.Context, path: Path, name: str = typer.Option(..., "--name")):
    """Import a strict UTF-8 CSV or flat JSON array, preserving original bytes."""
    emit(ctx, work(ctx).datasets.import_file(path, name))


@dataset_app.command("list")
@handled
def dataset_list(ctx: typer.Context, search: str = "", offset: int = 0, limit: int = 50):
    """List datasets using literal name search and stable pagination."""
    emit(ctx, work(ctx).datasets.list(search, offset, limit))


@dataset_app.command("show")
@handled
def dataset_show(ctx: typer.Context, dataset: str):
    """Show metadata and inferred columns by dataset name or UUID."""
    emit(ctx, work(ctx).datasets.get(dataset))


@dataset_app.command("preview")
@handled
def dataset_preview(ctx: typer.Context, dataset: str, offset: int = 0, limit: int = 20):
    """Preview up to 200 data records."""
    emit(ctx, work(ctx).datasets.preview(dataset, offset, limit))


@dataset_app.command("export")
@handled
def dataset_export(
    ctx: typer.Context,
    dataset: str,
    format: str = "csv",
    output: Path | None = None,
    spreadsheet_safe: bool = False,
):
    """Export CSV or JSON to stdout or a new file. Never overwrite a file."""
    save_export(output, work(ctx).datasets.export(dataset, format, spreadsheet_safe))


@dataset_app.command("source")
@handled
def dataset_source(ctx: typer.Context, dataset: str, output: Path):
    """Retrieve the exact original import bytes, verified by checksum."""
    save_export(output, work(ctx).datasets.source(dataset))


@dataset_app.command("delete")
@handled
def dataset_delete(
    ctx: typer.Context,
    dataset: str,
    yes: bool = typer.Option(False, "--yes", help="Confirm deletion. Dependencies block deletion."),
):
    """Delete an unreferenced dataset and its artifacts. Requires --yes."""
    emit(ctx, work(ctx).datasets.delete(dataset, confirmed=yes))


@validation_app.command("run")
@handled
def validation_run(
    ctx: typer.Context, dataset: str, rules: Path | None = None, definition: str | None = None
):
    """Validate using --rules FILE or --definition NAME. Exit 2 for failed validation."""
    result = work(ctx).validation.run(dataset, **config_or_definition(rules, definition))
    emit(ctx, result)
    if not result["passed"]:
        raise typer.Exit(2)


@validation_app.command("show")
@handled
def validation_show(ctx: typer.Context, run: str, offset: int = 0, limit: int = 50):
    """Inspect a run and a page of row-level issues."""
    emit(ctx, work(ctx).validation.get(run, offset, limit))


@validation_app.command("list")
@handled
def validation_list(ctx: typer.Context, offset: int = 0, limit: int = 50):
    """List validation runs."""
    emit(ctx, work(ctx).validation.list(offset, limit))


@pipeline_app.command("run")
@handled
def pipeline_run(
    ctx: typer.Context,
    dataset: str = typer.Option(...),
    output_name: str = typer.Option(...),
    config: Path | None = None,
    definition: str | None = None,
):
    """Run --config FILE or --definition NAME; produce a new --output-name dataset."""
    emit(
        ctx,
        work(ctx).pipelines.run(dataset, output_name, **config_or_definition(config, definition)),
    )


@pipeline_app.command("list")
@handled
def pipeline_list(ctx: typer.Context, offset: int = 0, limit: int = 50):
    """List pipeline execution records, including failures."""
    emit(ctx, work(ctx).pipelines.list(offset, limit))


@pipeline_app.command("show")
@handled
def pipeline_show(ctx: typer.Context, job: str):
    """Inspect a pipeline job and its exact configuration snapshot."""
    emit(ctx, work(ctx).pipelines.get(job))


@pipeline_app.command("recover")
@handled
def pipeline_recover(ctx: typer.Context, job: str, yes: bool = typer.Option(False, "--yes")):
    """Mark interrupted work failed. Any active execution loses permission to commit."""
    emit(ctx, work(ctx).pipelines.recover(job, yes))


@report_app.command("generate")
@handled
def report_generate(
    ctx: typer.Context,
    dataset: str,
    config: Path | None = None,
    definition: str | None = None,
    group_by: list[str] = typer.Option(None),
    sum_column: list[str] = typer.Option(None, "--sum"),
):
    """Profile a dataset, optionally using repeated --group-by and --sum options."""
    arguments = config_or_definition(config, definition)
    if group_by or sum_column:
        if config is not None or definition is not None:
            raise InputError("Do not combine inline metrics with --config or --definition")
        arguments["config"] = {
            "group_by": group_by or [],
            "metrics": [{"op": "sum", "column": c, "name": f"sum_{c}"} for c in (sum_column or [])],
        }
    emit(ctx, work(ctx).reports.generate(dataset, **arguments))


@report_app.command("list")
@handled
def report_list(ctx: typer.Context, offset: int = 0, limit: int = 50):
    """List generated reports."""
    emit(ctx, work(ctx).reports.list(offset, limit))


@report_app.command("show")
@handled
def report_show(ctx: typer.Context, report: str):
    """Show persisted report results and provenance."""
    emit(ctx, work(ctx).reports.get(report))


@report_app.command("export")
@handled
def report_export(
    ctx: typer.Context,
    report: str,
    format: str = "json",
    output: Path | None = None,
    spreadsheet_safe: bool = False,
):
    """Export the full JSON report or grouped CSV summary."""
    save_export(output, work(ctx).reports.export(report, format, spreadsheet_safe))


@definition_app.command("save")
@handled
def definition_save(ctx: typer.Context, kind: str, name: str, config: Path):
    """Save a validated configuration; kind is validation, pipeline, or report."""
    emit(ctx, work(ctx).definitions.save(kind, name, configuration(config)))


@definition_app.command("list")
@handled
def definition_list(ctx: typer.Context, kind: str, offset: int = 0, limit: int = 50):
    """List immutable saved definitions by kind."""
    emit(ctx, work(ctx).definitions.list(kind, offset, limit))


@definition_app.command("show")
@handled
def definition_show(ctx: typer.Context, kind: str, definition: str):
    """Show a reusable configuration."""
    emit(ctx, work(ctx).definitions.get(kind, definition))


@history_app.command("imports")
@handled
def history_imports(ctx: typer.Context, offset: int = 0, limit: int = 50):
    """List successful and failed imports."""
    emit(ctx, work(ctx).imports(offset, limit))


@history_app.command("delete")
@handled
def history_delete(
    ctx: typer.Context, kind: str, reference: str, yes: bool = typer.Option(False, "--yes")
):
    """Remove validation, job, report, or import history. Requires --yes."""
    emit(ctx, work(ctx).delete_history(kind, reference, confirmed=yes))


@app.command()
@handled
def serve(ctx: typer.Context, host: str = "127.0.0.1", port: int = 8000):
    """Start the local API and dashboard; apply pending migrations first."""
    import uvicorn

    from dataforge.api import create_app

    uvicorn.run(create_app(work(ctx).settings), host=host, port=port)


if __name__ == "__main__":
    app()
