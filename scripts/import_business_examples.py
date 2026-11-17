"""Import an optional fictional business workspace, using shared DataForge services.

Requires an explicit NEW directory, even if DATAFORGE_HOME is set. Existing
paths (including empty directories, files, and symlinks) are always refused.
No network, random input, existing database, or original sample files are used.
"""

import argparse
import json
from pathlib import Path

from dataforge.config import Settings
from dataforge.errors import Conflict, ForgeError
from dataforge.workspace import Workspace

BUNDLE = Path(__file__).resolve().parents[1] / "examples" / "small_business"


def configuration(relative: str) -> dict:
    return json.loads((BUNDLE / relative).read_text(encoding="utf-8"))


def build_workspace(home: Path) -> dict:
    """Exclusively reserve a fresh path before initializing any database or files.

    A failure leaves only the newly reserved directory for inspection; it never
    removes a workspace, retries against an existing path, or overwrites data.
    """
    target = home.expanduser().absolute()
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise Conflict(
            f"Refusing existing path: {target}. Choose a new workspace directory."
        ) from exc
    result = {
        "home": str(target),
        "raw": {},
        "clean": {},
        "validations": {},
        "jobs": {},
        "reports": {},
        "derived": {},
    }
    workspace = Workspace(Settings(home=target))
    try:
        workspace.initialize()
        for entry in configuration("manifest.json")["datasets"]:
            name = entry["name"]
            raw_name, clean_name = f"business_{name}_raw", f"business_{name}_clean"
            result["raw"][name] = workspace.datasets.import_file(BUNDLE / entry["file"], raw_name)
            for kind, folder in [
                ("validation", "rules"),
                ("pipeline", "pipelines"),
                ("report", "reports"),
            ]:
                workspace.definitions.save(
                    kind, f"business_{name}", configuration(f"{folder}/{name}.json")
                )
            raw_validation = workspace.validation.run(raw_name, definition=f"business_{name}")
            result["jobs"][name] = workspace.pipelines.run(
                raw_name, clean_name, definition=f"business_{name}"
            )
            result["clean"][name] = workspace.datasets.get(clean_name)
            clean_validation = workspace.validation.run(clean_name, definition=f"business_{name}")
            result["validations"][name] = {"raw": raw_validation, "clean": clean_validation}
            result["reports"][name] = workspace.reports.generate(
                clean_name, definition=f"business_{name}"
            )
        for name, input_name in [
            ("paid_expenses", "expenses"),
            ("inventory_balances", "inventory_movements"),
        ]:
            workspace.definitions.save(
                "pipeline", f"business_{name}", configuration(f"pipelines/{name}.json")
            )
            job = workspace.pipelines.run(
                f"business_{input_name}_clean", f"business_{name}", definition=f"business_{name}"
            )
            result["jobs"][name] = job
            result["derived"][name] = workspace.datasets.get(job["output_id"])
        for name, input_name in [
            ("paid_expenses", "paid_expenses"),
            ("sales_by_category", "sales_clean"),
        ]:
            workspace.definitions.save(
                "report", f"business_{name}", configuration(f"reports/{name}.json")
            )
            result["reports"][name] = workspace.reports.generate(
                f"business_{input_name}", definition=f"business_{name}"
            )
        # Never replace a file, even inside the directory we just reserved.
        with (target / "business-example.json").open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
        return result
    finally:
        workspace.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        required=True,
        type=Path,
        help="New, nonexistent directory for the optional example workspace.",
    )
    args = parser.parse_args()
    try:
        result = build_workspace(args.home)
    except (ForgeError, OSError, ValueError) as exc:
        parser.exit(
            1,
            f"Error: {exc}\nNo existing workspace was changed; a newly reserved directory may remain after a failed build.\n",
        )
    summary = {
        "home": result["home"],
        "raw_rows": {k: d["row_count"] for k, d in result["raw"].items()},
        "clean_rows": {k: d["row_count"] for k, d in result["clean"].items()},
        "reports": {k: d["id"] for k, d in result["reports"].items()},
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
