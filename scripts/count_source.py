"""Count physical/nonblank source lines, excluding generated migrations and data."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = {".py", ".html", ".css"}


def main() -> None:
    totals = [0, 0]
    for directory in ("src/dataforge", "tests", "scripts"):
        files = [
            file
            for file in (ROOT / directory).rglob("*")
            if file.is_file()
            and file.suffix in EXTENSIONS
            and "__pycache__" not in file.parts
            and "versions" not in file.parts
        ]
        lines = [line for file in files for line in file.read_text().splitlines()]
        physical, nonblank = len(lines), sum(bool(line.strip()) for line in lines)
        totals[0] += physical
        totals[1] += nonblank
        print(f"{directory}: {physical} physical / {nonblank} nonblank ({len(files)} files)")
    print(f"Total: {totals[0]} physical / {totals[1]} nonblank source and test lines")
    print(
        "Excludes dependencies, build artifacts, generated migration revisions, docs, configs, and data."
    )


if __name__ == "__main__":
    main()
