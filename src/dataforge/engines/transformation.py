"""Validated deterministic steps operating on copies of immutable input records."""

from datetime import datetime

from dataforge.config import Settings
from dataforge.engines.analytics import aggregate
from dataforge.engines.expressions import Expression
from dataforge.engines.parsing import check_size, columns_checked
from dataforge.engines.validation import require_columns
from dataforge.engines.values import COMPARISONS, Row, decimal_text, missing, number, stable
from dataforge.errors import InputError
from dataforge.schemas import PipelineConfig


def plan(columns: list[str], config: PipelineConfig) -> list[str]:
    """Validate every step and evolving column schema before executing any row."""
    columns = list(columns)
    for index, step in enumerate(config.steps, 1):
        try:
            requested = list(getattr(step, "columns", None) or [])
            if hasattr(step, "column") and step.op != "calculate":
                requested.append(step.column)
            require_columns(columns, requested)
            if step.op == "rename":
                require_columns(columns, list(step.mapping))
                columns = [step.mapping.get(c, c) for c in columns]
            elif step.op == "select":
                columns = list(step.columns)
            elif step.op == "drop":
                columns = [c for c in columns if c not in step.columns]
            elif step.op == "calculate":
                if step.column in columns:
                    raise InputError("Calculated columns must have a new name")
                Expression(step.expression, columns)
                columns.append(step.column)
            elif step.op == "aggregate":
                columns, _ = aggregate(columns, [], step.group_by, step.metrics)
            columns_checked(columns)
        except InputError as exc:
            raise InputError(f"Step {index} ({step.op}): {exc}") from exc
    return columns


def transform(
    columns: list[str], rows: list[Row], config: PipelineConfig, settings: Settings
) -> tuple[list[str], list[Row]]:
    plan(columns, config)
    columns, rows = list(columns), [dict(row) for row in rows]
    for index, step in enumerate(config.steps, 1):
        try:
            if step.op == "rename":
                columns = [step.mapping.get(c, c) for c in columns]
                rows = [{step.mapping.get(c, c): v for c, v in r.items()} for r in rows]
            elif step.op in {"select", "drop"}:
                columns = (
                    list(step.columns)
                    if step.op == "select"
                    else [c for c in columns if c not in step.columns]
                )
                rows = [{c: r[c] for c in columns} for r in rows]
            elif step.op == "filter":
                rows = [r for r in rows if matches(r[step.column], step)]
            elif step.op == "sort":
                present = [r for r in rows if all(not missing(r[c]) for c in step.columns)]
                absent = [r for r in rows if any(missing(r[c]) for c in step.columns)]
                rows = (
                    sorted(
                        present,
                        key=lambda r: tuple(
                            number(r[c]) if step.numeric else str(r[c]) for c in step.columns
                        ),
                        reverse=step.descending,
                    )
                    + absent
                )
            elif step.op == "convert":
                for row_number, row in enumerate(rows, 1):
                    try:
                        row[step.column] = convert(row[step.column], step.type, step.format)
                    except (InputError, ValueError, OverflowError) as exc:
                        if step.on_error == "null":
                            row[step.column] = None
                        else:
                            raise InputError(f"Record {row_number}, {step.column}: {exc}") from exc
            elif step.op == "missing":
                if step.strategy == "drop":
                    rows = [r for r in rows if all(not missing(r[c]) for c in step.columns)]
                else:
                    for row in rows:
                        for column in step.columns:
                            if missing(row[column]):
                                row[column] = step.value
            elif step.op == "normalize":
                for row in rows:
                    for column in step.columns:
                        if not missing(row[column]):
                            text = str(row[column])
                            row[column] = (
                                " ".join(text.split())
                                if step.mode == "collapse"
                                else getattr(text, step.mode)()
                            )
            elif step.op == "deduplicate":
                seen, kept = set(), []
                for row in rows:
                    key = stable([row[c] for c in (step.columns or columns)])
                    if key not in seen:
                        seen.add(key)
                        kept.append(row)
                rows = kept
            elif step.op == "calculate":
                expression = Expression(step.expression, columns)
                for row_number, row in enumerate(rows, 1):
                    try:
                        row[step.column] = expression.evaluate(row)
                    except InputError as exc:
                        raise InputError(f"Record {row_number}: {exc}") from exc
                columns.append(step.column)
            elif step.op == "aggregate":
                columns, rows = aggregate(columns, rows, step.group_by, step.metrics)
            check_size(rows, columns, settings)
        except InputError as exc:
            raise InputError(f"Step {index} ({step.op}): {exc}") from exc
    return columns, rows


def matches(value, step) -> bool:
    if step.operator == "is_missing":
        return missing(value)
    if step.operator == "not_missing":
        return not missing(value)
    if missing(value) or missing(step.value):
        return (
            step.operator == "eq"
            and missing(value)
            and missing(step.value)
            or step.operator == "ne"
            and missing(value) != missing(step.value)
        )
    if step.operator == "contains":
        return str(step.value) in str(value)
    left, right = (number(value), number(step.value)) if step.numeric else (value, step.value)
    try:
        return COMPARISONS[step.operator](left, right)
    except TypeError as exc:
        raise InputError(
            "Filter values have incompatible types; use numeric=true for numeric comparison"
        ) from exc


def convert(value, target: str, date_format: str):
    if missing(value):
        return None
    if target == "string":
        return str(value)
    if target == "integer":
        numeric = number(value)
        if numeric != numeric.to_integral_value():
            raise InputError("Cannot convert fractional value to integer without data loss")
        return int(numeric)
    if target == "decimal":
        return decimal_text(number(value))
    if target == "boolean":
        if str(value).lower() in {"true", "1"}:
            return True
        if str(value).lower() in {"false", "0"}:
            return False
        raise InputError("Boolean conversion supports true/false/1/0")
    return datetime.strptime(str(value), date_format).date().isoformat()
