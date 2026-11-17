"""Read-only validation. Row numbers are one-based data-record numbers."""

from datetime import datetime

from dataforge.engines.values import COMPARISONS, Row, missing, number, stable
from dataforge.errors import InputError
from dataforge.schemas import Rule, RuleSet


def require_columns(columns: list[str], requested: list[str]) -> None:
    unknown = set(requested) - set(columns)
    if unknown:
        raise InputError(f"Unknown columns: {', '.join(sorted(unknown))}")


def validate_rows(columns: list[str], rows: list[Row], config: RuleSet) -> list[dict]:
    issues = []
    for rule_index, rule in enumerate(config.rules, 1):
        require_columns(columns, [c for c in (rule.column, rule.other_column) if c is not None])
        seen = set()
        for index, row in enumerate(rows, 1):
            value = row.get(rule.column) if rule.column is not None else None
            description = failure(rule, row, value, seen)
            if description is not None:
                if len(issues) >= 50000:
                    raise InputError(
                        "Validation exceeds 50,000 issues; narrow the rule set or dataset"
                    )
                issues.append(
                    {
                        "rule": f"{rule_index}:{rule.kind}",
                        "column": rule.column,
                        "row": index,
                        "severity": rule.severity,
                        "description": description,
                    }
                )
    return issues


def failure(rule: Rule, row: Row, value, seen: set) -> str | None:
    if rule.kind == "required":
        return "Required value is missing" if missing(value) else None
    if rule.kind == "duplicate_rows":
        key = stable(row)
        duplicate = key in seen
        seen.add(key)
        return "Duplicate of an earlier record" if duplicate else None
    # Missing values are checked only by required; combine rules explicitly.
    if missing(value):
        return None
    if rule.kind == "unique":
        key = stable(value)
        duplicate = key in seen
        seen.add(key)
        return "Value duplicates an earlier record" if duplicate else None
    if rule.kind == "allowed":
        return None if value in (rule.values or []) else "Value is not in the allowed set"
    if rule.kind == "numeric":
        try:
            number(value)
        except InputError:
            return "Value is not a supported finite number"
    if rule.kind == "date":
        try:
            datetime.strptime(str(value), rule.format)
        except ValueError:
            return f"Date does not match {rule.format}"
    if rule.kind in {"range", "length"}:
        try:
            checked = number(value) if rule.kind == "range" else len(str(value))
        except InputError:
            return "Cannot check range on a nonnumeric value"
        if rule.minimum is not None and checked < rule.minimum:
            return f"Value is below minimum {rule.minimum}"
        if rule.maximum is not None and checked > rule.maximum:
            return f"Value exceeds maximum {rule.maximum}"
    if rule.kind == "compare":
        other = row[rule.other_column]
        if missing(other):
            return "Comparison field is missing"
        try:
            left, right = number(value), number(other)
        except InputError:
            left, right = str(value), str(other)
        if not COMPARISONS[rule.operator](left, right):
            return f"Expected {rule.column} {rule.operator} {rule.other_column}"
    return None
