"""Strict bounded imports: reject malformed records; preserve all valid rows."""

import csv
import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from dataforge.config import Settings
from dataforge.engines.values import Row, decimal_text, missing, number
from dataforge.errors import InputError

MAX_COLUMNS = 1000


def columns_checked(columns: list[str]) -> list[str]:
    if not columns or len(columns) > MAX_COLUMNS:
        raise InputError(f"Expected between 1 and {MAX_COLUMNS} columns")
    if any(not isinstance(c, str) or not c.strip() or len(c) > 200 for c in columns):
        raise InputError("Column names must be nonblank strings of at most 200 characters")
    if len(set(columns)) != len(columns):
        raise InputError("Duplicate column names are not allowed")
    return columns


def parse_data(data: bytes, filename: str, settings: Settings) -> tuple[list[str], list[Row]]:
    if not data:
        raise InputError("The input file is empty")
    if len(data) > settings.max_file_bytes:
        raise InputError(f"File exceeds {settings.max_file_bytes} byte limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError("Input must be UTF-8 encoded (a UTF-8 BOM is allowed)") from exc
    if "\x00" in text:
        raise InputError("NUL bytes are not allowed")
    extension = Path(filename).suffix.lower()
    try:
        if extension == ".csv":
            reader = csv.reader(io.StringIO(text, newline=""), strict=True)
            columns = columns_checked(next(reader))
            rows = []
            for index, cells in enumerate(reader, 1):
                if len(cells) != len(columns):
                    raise InputError(
                        f"Record {index} has {len(cells)} fields; expected {len(columns)}"
                    )
                rows.append(
                    dict(zip(columns, (None if missing(v) else v for v in cells), strict=True))
                )
                check_size(rows, columns, settings)
            return columns, rows
        if extension == ".json":

            def reject_constant(value):
                raise InputError(f"Non-finite JSON number {value} is not allowed")

            def pairs_unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise InputError(f"Duplicate JSON key: {key}")
                    result[key] = value
                return result

            values = json.loads(
                text,
                parse_float=Decimal,
                parse_int=Decimal,
                parse_constant=reject_constant,
                object_pairs_hook=pairs_unique,
            )
            if not isinstance(values, list) or not values:
                raise InputError("JSON must be a nonempty array of flat objects")
            if len(values) > settings.max_rows:
                raise InputError(f"Dataset exceeds {settings.max_rows} row limit")
            columns = []
            seen = set()
            for index, row in enumerate(values, 1):
                if not isinstance(row, dict) or not row:
                    raise InputError(f"Record {index} must be a nonempty object")
                for key, value in row.items():
                    if isinstance(value, (list, dict)):
                        raise InputError(
                            f"Record {index}, column {key}: nested values are not supported"
                        )
                    if key not in seen:
                        columns.append(key)
                        seen.add(key)
                    if isinstance(value, Decimal):
                        row[key] = decimal_text(number(value))
            columns_checked(columns)
            check_size(values, columns, settings)
            return columns, [
                {c: None if missing(row.get(c)) else row[c] for c in columns} for row in values
            ]
        raise InputError("Only .csv and .json input files are supported")
    except (csv.Error, json.JSONDecodeError, StopIteration, RecursionError) as exc:
        raise InputError(f"Malformed {extension or 'input'} file: {exc}") from exc


def check_size(rows: list, columns: list[str], settings: Settings) -> None:
    if len(rows) > settings.max_rows or len(rows) * len(columns) > settings.max_cells:
        raise InputError(
            f"Dataset exceeds resource limits ({settings.max_rows} rows / {settings.max_cells} cells)"
        )


def infer_type(values: list) -> str:
    present = [v for v in values if not missing(v)]
    if not present:
        return "unknown"
    if all(isinstance(v, bool) or str(v).lower() in {"true", "false"} for v in present):
        return "boolean"
    try:
        nums = [number(v) for v in present]
        return "integer" if all(v == v.to_integral_value() for v in nums) else "decimal"
    except InputError:
        pass
    try:
        for value in present:
            date.fromisoformat(str(value))
        return "date"
    except ValueError:
        return "string"


def column_metadata(columns: list[str], rows: list[Row]) -> list[dict]:
    return [
        {
            "name": column,
            "position": index,
            "inferred_type": infer_type([r[column] for r in rows]),
            "missing_count": sum(missing(r[column]) for r in rows),
        }
        for index, column in enumerate(columns)
    ]
