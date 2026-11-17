"""SQLite integration and artifact preservation tests; each workspace is temporary."""

import csv
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from dataforge.errors import Conflict, InputError, NotFound
from dataforge.models import Dataset
from dataforge.storage import checksum


def artifact_files(workspace):
    return sorted(p for p in workspace.storage.root.rglob("*") if p.is_file())


def test_metadata_preview_checksum_and_original(workspace, sales):
    source = Path(__file__).parent / "fixtures" / "sales.csv"
    assert sales["row_count"] == 5
    assert sales["checksum"] == checksum(source.read_bytes())
    assert workspace.datasets.source("sales") == source.read_bytes()
    assert workspace.datasets.preview(sales["id"], 2, 2)["items"][0]["id"] == "3"
    assert sales["columns"][2]["inferred_type"] == "decimal"
    assert sales["columns"][2]["missing_count"] == 1
    assert workspace.imports()["items"][0]["status"] == "succeeded"


def test_json_import_unicode_and_missing_union(workspace):
    result = workspace.datasets.import_file(
        Path(__file__).parent / "fixtures" / "people.json", "people"
    )
    assert result["row_count"] == 2
    rows = workspace.datasets.preview("people")["items"]
    assert rows[0]["active"] is None
    assert rows[1]["name"] == "Bô"
    assert rows[0]["amount"] == "0.10"


def test_duplicate_name_is_not_silent_retry(workspace, sales):
    files = artifact_files(workspace)
    with pytest.raises(Conflict):
        workspace.datasets.import_bytes(b"a\n1", "x.csv", "sales")
    assert workspace.datasets.list()["total"] == 1
    assert artifact_files(workspace) == files
    assert workspace.imports()["items"][0]["status"] == "failed"


def test_bad_import_is_recorded_without_dataset_or_artifacts(workspace):
    with pytest.raises(InputError):
        workspace.datasets.import_bytes(b"a,b\n1", "bad.csv", "bad")
    assert workspace.datasets.list()["total"] == 0
    assert artifact_files(workspace) == []
    assert "Record 1" in workspace.imports()["items"][0]["error"]


def test_import_artifact_write_failure_cleans_files(workspace):
    with patch.object(workspace.storage, "write_rows", side_effect=OSError("disk full")):
        with pytest.raises(InputError):
            workspace.datasets.import_bytes(b"a\n1", "test.csv", "x")
    assert artifact_files(workspace) == []
    assert workspace.datasets.list()["total"] == 0
    assert workspace.imports()["items"][0]["status"] == "failed"


def test_database_failure_after_insert_rolls_back_and_cleans(workspace):
    original = workspace.datasets.insert

    def broken(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected failure after flush")

    with patch.object(workspace.datasets, "insert", side_effect=broken):
        with pytest.raises(RuntimeError):
            workspace.datasets.import_bytes(b"a\n1", "test.csv", "x")
    assert workspace.datasets.list()["total"] == 0
    assert artifact_files(workspace) == []


def test_source_filename_cannot_control_artifact_path(workspace):
    dataset = workspace.datasets.import_bytes(b"a\n1", "../../escape.csv", "safe")
    assert dataset["source_filename"] == "escape.csv"
    assert all(path.is_relative_to(workspace.settings.home) for path in artifact_files(workspace))
    with pytest.raises(InputError):
        workspace.storage.path("../../outside")


def test_tampered_artifact_is_detected(workspace, sales):
    with workspace.db.session() as session:
        dataset = workspace.datasets.resolve(session, "sales")
        artifact = next(a for a in dataset.artifacts if a.kind == "processed")
        workspace.storage.path(artifact.path).write_bytes(b"{}\n")
    with pytest.raises(InputError, match="checksum"):
        workspace.datasets.preview("sales")


def test_search_is_literal_and_pagination_is_stable(workspace):
    for name in ["a%", "ab", "ac", "a_"]:
        workspace.datasets.import_bytes(b"a\n1", "x.csv", name)
    assert workspace.datasets.list("% ")["total"] == 0
    assert workspace.datasets.list("%")["total"] == 1
    assert workspace.datasets.list("_")["total"] == 1
    first = workspace.datasets.list(limit=2)
    second = workspace.datasets.list(offset=2, limit=2)
    assert first["total"] == 4
    assert not {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]}


@pytest.mark.parametrize(("offset", "limit"), [(-1, 20), (0, 0), (0, 201)])
def test_pagination_rejected(workspace, sales, offset, limit):
    with pytest.raises(InputError):
        workspace.datasets.list(offset=offset, limit=limit)
    with pytest.raises(InputError):
        workspace.datasets.preview("sales", offset, limit)


def test_validation_persistence_and_ascending_issue_pagination(workspace, sales):
    run = workspace.validation.run("sales", {"rules": [{"kind": "required", "column": "customer"}]})
    assert not run["passed"]
    assert run["issue_count"] == 2
    one = workspace.validation.get(run["id"], 0, 1)
    two = workspace.validation.get(run["id"], 1, 1)
    assert one["issues"]["items"][0]["row"] == 3
    assert two["issues"]["items"][0]["row"] == 4
    assert one["dataset_id"] == sales["id"]
    assert workspace.datasets.preview("sales")["total"] == 5


def test_warnings_do_not_fail_validation(workspace, sales):
    run = workspace.validation.run(
        "sales", {"rules": [{"kind": "required", "column": "customer", "severity": "warning"}]}
    )
    assert run["passed"] and run["issue_count"] == 2


def test_invalid_column_validation_rolls_back(workspace, sales):
    with pytest.raises(InputError, match="Unknown columns"):
        workspace.validation.run("sales", {"rules": [{"kind": "required", "column": "unknown"}]})
    assert workspace.validation.list()["total"] == 0


def test_saved_definition_snapshot_and_duplicate_protection(workspace, sales):
    config = {"rules": [{"kind": "required", "column": "id"}]}
    saved = workspace.definitions.save("validation", "ids", config)
    config["rules"][0]["column"] = "unknown"
    run = workspace.validation.run("sales", definition="ids")
    assert run["definition_id"] == saved["id"]
    assert run["config"]["rules"][0]["column"] == "id"
    assert workspace.definitions.list("validation")["total"] == 1
    with pytest.raises(Conflict):
        workspace.definitions.save(
            "validation", "ids", {"rules": [{"kind": "required", "column": "id"}]}
        )


def test_successful_pipeline_and_source_preservation(workspace, sales):
    before = workspace.datasets.source("sales")
    config = {
        "steps": [
            {"op": "deduplicate"},
            {"op": "missing", "columns": ["amount"], "strategy": "drop"},
            {"op": "calculate", "column": "total", "expression": "amount * quantity"},
        ]
    }
    saved = workspace.definitions.save("pipeline", "clean", config)
    job = workspace.pipelines.run("sales", "clean-sales", definition=saved["id"])
    assert job["status"] == "succeeded" and job["finished_at"]
    assert workspace.datasets.get(job["output_id"])["parent_id"] == sales["id"]
    rows = workspace.datasets.preview("clean-sales")["items"]
    assert len(rows) == 3 and rows[0]["total"] == "20.20"
    assert workspace.datasets.source("sales") == before
    assert workspace.datasets.preview("sales")["total"] == 5


def test_failed_pipeline_has_no_partial_results(workspace, sales):
    before = artifact_files(workspace)
    config = {
        "steps": [
            {"op": "rename", "mapping": {"amount": "value"}},
            {"op": "calculate", "column": "bad", "expression": "value / 0"},
        ]
    }
    with pytest.raises(InputError, match="Step 2"):
        workspace.pipelines.run("sales", "failed-output", config)
    job = workspace.pipelines.list()["items"][0]
    assert job["status"] == "failed" and job["output_id"] is None
    assert job["finished_at"] and "division" in job["error"]
    assert workspace.datasets.list()["total"] == 1
    assert artifact_files(workspace) == before


def test_pipeline_database_failure_rolls_back_output(workspace, sales):
    before = artifact_files(workspace)
    original = workspace.datasets.insert

    def broken(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected failure")

    with patch.object(workspace.datasets, "insert", side_effect=broken):
        with pytest.raises(RuntimeError):
            workspace.pipelines.run("sales", "output", {"steps": [{"op": "deduplicate"}]})
    assert workspace.pipelines.list()["items"][0]["status"] == "failed"
    assert workspace.datasets.list()["total"] == 1
    assert artifact_files(workspace) == before


def test_failed_pipeline_can_be_retried_safely(workspace, sales):
    with pytest.raises(InputError):
        workspace.pipelines.run(
            "sales", "clean", {"steps": [{"op": "convert", "column": "date", "type": "date"}]}
        )
    result = workspace.pipelines.run("sales", "clean", {"steps": [{"op": "deduplicate"}]})
    assert result["status"] == "succeeded"
    assert workspace.pipelines.list()["total"] == 2


def test_report_profile_grouped_metrics_and_exports(workspace, sales):
    config = {
        "group_by": ["category"],
        "metrics": [
            {"op": "sum", "column": "amount", "name": "total"},
            {"op": "avg", "column": "amount", "name": "average"},
            {"op": "count", "name": "records"},
        ],
    }
    definition = workspace.definitions.save("report", "sales-by-category", config)
    report = workspace.reports.generate("sales", definition=definition["id"])
    result = report["result"]
    assert result["row_count"] == 5
    assert result["columns"]["amount"]["missing"] == 1
    assert result["columns"]["amount"]["numeric"]["sum"] == "36.90"
    assert result["groups"] == [
        {"category": "Food", "total": "6.60", "average": "3.30", "records": 3},
        {"category": "Office", "total": "30.30", "average": "15.15", "records": 2},
    ]
    assert workspace.reports.get(report["id"])["result"] == result
    assert json.loads(workspace.reports.export(report["id"]))["result"] == result
    csv_rows = list(
        csv.DictReader(io.StringIO(workspace.reports.export(report["id"], "csv").decode()))
    )
    assert csv_rows[0]["total"] == "6.60"


def test_report_invalid_numeric_metric_fails_without_output(workspace):
    workspace.datasets.import_bytes(b"amount\nbad\n1", "x.csv", "x")
    profile = workspace.reports.generate("x")["result"]
    assert profile["columns"]["amount"]["numeric_invalid"] == 1
    with pytest.raises(InputError):
        workspace.reports.generate(
            "x", {"metrics": [{"op": "sum", "column": "amount", "name": "total"}]}
        )
    assert workspace.reports.list()["total"] == 1


def test_empty_csv_with_headers_and_empty_output(workspace):
    dataset = workspace.datasets.import_bytes(b"a,b\n", "x.csv", "empty")
    assert dataset["row_count"] == 0
    assert workspace.datasets.export("empty") == b"a,b\n"
    assert workspace.reports.generate("empty")["result"]["groups"] == [{"row_count": 0}]


def test_csv_json_exports_and_spreadsheet_opt_in(workspace):
    workspace.datasets.import_bytes(b'a,b\n"=SUM(1,2)","comma,quote"\n', "x.csv", "x")
    assert workspace.datasets.export("x").startswith(b'a,b\n"=SUM')
    assert b"'=SUM" in workspace.datasets.export("x", spreadsheet_safe=True)
    assert json.loads(workspace.datasets.export("x", "json"))[0]["b"] == "comma,quote"
    with pytest.raises(InputError):
        workspace.datasets.export("x", "exe")


def test_delete_requires_confirmation_and_removes_artifacts(workspace, sales):
    with pytest.raises(Conflict):
        workspace.datasets.delete("sales")
    workspace.datasets.delete("sales", True)
    assert artifact_files(workspace) == []
    assert workspace.imports()["items"][0]["dataset_id"] is None
    with pytest.raises(NotFound):
        workspace.datasets.get("sales")


@pytest.mark.parametrize("dependency", ["validation", "report", "job"])
def test_dataset_dependency_protection(workspace, sales, dependency):
    if dependency == "validation":
        result = workspace.validation.run(
            "sales", {"rules": [{"kind": "required", "column": "id"}]}
        )
    elif dependency == "report":
        result = workspace.reports.generate("sales")
    else:
        result = workspace.pipelines.run("sales", "derived", {"steps": [{"op": "deduplicate"}]})
    with pytest.raises(Conflict):
        workspace.datasets.delete("sales", True)
    workspace.delete_history(dependency, result["id"], True)
    if dependency == "job":
        with pytest.raises(Conflict, match="datasets"):
            workspace.datasets.delete("sales", True)
        workspace.datasets.delete("derived", True)
    workspace.datasets.delete("sales", True)


def test_foreign_keys_and_transaction_context(workspace):
    with pytest.raises(RuntimeError):
        with workspace.db.session() as session:
            session.add(
                Dataset(name="rolled-back", source_filename="x", row_count=0, checksum="0" * 64)
            )
            session.flush()
            raise RuntimeError("abort")
    with workspace.db.session() as session:
        assert session.scalar(select(Dataset)) is None
        assert session.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


@pytest.mark.parametrize(
    "method",
    [
        lambda w: w.datasets.get("missing"),
        lambda w: w.validation.get("missing"),
        lambda w: w.pipelines.get("missing"),
        lambda w: w.reports.get("missing"),
        lambda w: w.definitions.get("validation", "missing"),
    ],
)
def test_not_found_errors(workspace, method):
    with pytest.raises(NotFound):
        method(workspace)


def test_recover_interrupted_job_and_release_history(workspace, sales):
    from dataforge.models import Job

    with workspace.db.session() as session:
        job = Job(input_id=sales["id"], config={"steps": [{"op": "deduplicate"}]}, status="running")
        session.add(job)
        session.flush()
        job_id = job.id
    with pytest.raises(Conflict):
        workspace.delete_history("job", job_id, True)
    with pytest.raises(Conflict):
        workspace.pipelines.recover(job_id)
    recovered = workspace.pipelines.recover(job_id, True)
    assert recovered["status"] == "failed" and recovered["finished_at"]
    with pytest.raises(Conflict):
        workspace.pipelines.recover(job_id, True)
    workspace.delete_history("job", job_id, True)
    workspace.datasets.delete("sales", True)


def test_recovery_revokes_live_worker_commit(workspace, sales):
    original = workspace.storage.write_rows

    def recover_before_commit(rows):
        job = workspace.pipelines.list()["items"][0]
        workspace.pipelines.recover(job["id"], True)
        return original(rows)

    before = artifact_files(workspace)
    with patch.object(workspace.storage, "write_rows", side_effect=recover_before_commit):
        with pytest.raises(InputError, match="recovered"):
            workspace.pipelines.run("sales", "cancelled", {"steps": [{"op": "deduplicate"}]})
    assert workspace.datasets.list()["total"] == 1
    assert workspace.pipelines.list()["items"][0]["status"] == "failed"
    assert artifact_files(workspace) == before
