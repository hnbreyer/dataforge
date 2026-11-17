"""Verify documented commands in a disposable workspace without starting a server."""

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with TemporaryDirectory(prefix="dataforge-example-") as directory:
        home = Path(directory)

        def command(*args: str, expected: int = 0):
            result = subprocess.run(
                [sys.executable, "-m", "dataforge.cli", "--home", str(home), "--json", *args],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != expected:
                raise RuntimeError(f"Command {args!r} failed: {result.stderr}")
            return json.loads(result.stdout) if result.stdout else None

        command("init")
        imported = command("dataset", "import", "examples/sales.csv", "--name", "sales")
        assert imported["row_count"] == 5
        validation = command(
            "validate", "run", "sales", "--rules", "examples/sales-rules.json", expected=2
        )
        assert validation["issue_count"] == 4 and not validation["passed"]
        job = command(
            "pipeline",
            "run",
            "--dataset",
            "sales",
            "--output-name",
            "clean-sales",
            "--config",
            "examples/clean-sales.json",
        )
        assert job["status"] == "succeeded"
        report = command(
            "report", "generate", "clean-sales", "--config", "examples/sales-report.json"
        )
        groups = report["result"]["groups"]
        assert [(g["category"], g["total"]) for g in groups] == [
            ("food", "9.90"),
            ("office", "40.40"),
        ]
        exported = home / "export.csv"
        command("dataset", "export", "clean-sales", "--output", str(exported))
        assert len(exported.read_text().splitlines()) == 4
        original = home / "original.csv"
        command("dataset", "source", "sales", str(original))
        assert original.read_bytes() == (ROOT / "examples/sales.csv").read_bytes()
        assert command("dataset", "show", "sales")["row_count"] == 5
        print("Documented CLI workflow passed: import, 4 validation issues, 3 output rows,")
        print("food=9.90, office=40.40, export, and byte-identical preserved source.")


if __name__ == "__main__":
    main()
