import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataforge.cli import app

runner = CliRunner()


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path / "cli-workspace"))

    def invoke(*arguments, code=0):
        result = runner.invoke(app, ["--json", *arguments])
        assert result.exit_code == code, result.output + repr(result.exception)
        return result

    invoke("init")
    return invoke


def fixture_path():
    return str(Path(__file__).parent / "fixtures" / "sales.csv")


def test_cli_end_to_end(cli, tmp_path):
    imported = json.loads(cli("dataset", "import", fixture_path(), "--name", "sales").stdout)
    assert imported["row_count"] == 5
    assert json.loads(cli("dataset", "list").stdout)["total"] == 1
    assert json.loads(cli("dataset", "show", "sales").stdout)["name"] == "sales"
    assert json.loads(cli("dataset", "preview", "sales", "--limit", "1").stdout)["limit"] == 1
    rules = tmp_path / "rules.json"
    rules.write_text('{"rules":[{"kind":"required","column":"customer"}]}')
    run = json.loads(cli("validate", "run", "sales", "--rules", str(rules), code=2).stdout)
    assert run["issue_count"] == 2
    assert json.loads(cli("validate", "show", run["id"]).stdout)["issues"]["total"] == 2
    pipeline = tmp_path / "pipeline.json"
    pipeline.write_text('{"steps":[{"op":"deduplicate"}]}')
    cli("definition", "save", "pipeline", "clean", str(pipeline))
    job = json.loads(
        cli(
            "pipeline",
            "run",
            "--dataset",
            "sales",
            "--output-name",
            "clean",
            "--definition",
            "clean",
        ).stdout
    )
    assert job["status"] == "succeeded"
    assert json.loads(cli("pipeline", "show", job["id"]).stdout)["output_id"]
    report = json.loads(
        cli("report", "generate", "clean", "--group-by", "category", "--sum", "amount").stdout
    )
    assert report["result"]["row_count"] == 4
    output = tmp_path / "export.csv"
    cli("dataset", "export", "clean", "--output", str(output))
    assert len(output.read_text().splitlines()) == 5
    cli("dataset", "export", "sales", "--output", str(output), code=1)
    cli("report", "export", report["id"], "--output", str(tmp_path / "report.json"))
    cli("dataset", "source", "sales", str(tmp_path / "source.csv"))
    assert (tmp_path / "source.csv").read_bytes() == Path(fixture_path()).read_bytes()
    assert json.loads(cli("status").stdout)["datasets"] == 2


def test_cli_errors_to_stderr_and_deletion_confirmation(cli):
    result = cli("dataset", "show", "missing", code=1)
    assert "not found" in result.stderr and not result.stdout
    cli("dataset", "import", fixture_path(), "--name", "sales")
    cli("dataset", "delete", "sales", code=1)
    cli("dataset", "delete", "sales", "--yes")
    assert json.loads(cli("history", "imports").stdout)["items"][0]["dataset_id"] is None


def test_cli_config_validation(cli, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("[]")
    result = cli("definition", "save", "validation", "bad", str(path), code=1)
    assert "JSON object" in result.stderr
    path.write_text("{broken")
    cli("definition", "save", "validation", "bad", str(path), code=1)


def test_cli_global_home_isolation(tmp_path):
    home = tmp_path / "custom"
    result = runner.invoke(app, ["--home", str(home), "init"])
    assert result.exit_code == 0
    assert (home / "dataforge.db").is_file()


def test_cli_help_is_available_without_database():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dataset" in result.stdout
