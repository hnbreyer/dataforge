"""Deterministic numeric and categorical summaries over actual records."""

from collections import Counter

from dataforge.engines.validation import require_columns
from dataforge.engines.values import Row, missing, number, numeric_summary, stable
from dataforge.errors import InputError
from dataforge.schemas import Metric, ReportConfig


def aggregate(
    columns: list[str], rows: list[Row], group_by: list[str], metrics: list[Metric]
) -> tuple[list[str], list[Row]]:
    require_columns(columns, group_by + [m.column for m in metrics if m.column is not None])
    output_columns = group_by + [m.name for m in metrics]
    if len(output_columns) != len(set(output_columns)):
        raise InputError("Group columns and metric names must be unique")
    groups: dict[str, tuple[list, list[Row]]] = {}
    if not group_by:
        groups["[]"] = ([], [])
    for row in rows:
        values = [row[c] for c in group_by]
        key = stable(values)
        if key not in groups:
            groups[key] = (values, [])
        groups[key][1].append(row)
    result = []
    for key in sorted(groups):
        group_values, members = groups[key]
        item = dict(zip(group_by, group_values, strict=True))
        for metric in metrics:
            if metric.op == "count":
                item[metric.name] = (
                    len(members)
                    if metric.column is None
                    else sum(not missing(r[metric.column]) for r in members)
                )
            else:
                values = [
                    number(r[metric.column]) for r in members if not missing(r[metric.column])
                ]
                item[metric.name] = numeric_summary(values)[metric.op]
        result.append(item)
    return output_columns, result


def profile(columns: list[str], rows: list[Row], config: ReportConfig) -> dict:
    require_columns(
        columns, config.group_by + [m.column for m in config.metrics if m.column is not None]
    )
    summaries = {}
    for column in columns:
        present = [r[column] for r in rows if not missing(r[column])]
        counts = Counter(stable(v) for v in present)
        # Keep scalar types intact in frequencies; no display-string collisions.
        values_by_key = {stable(value): value for value in present}
        numeric, invalid = [], 0
        for value in present:
            try:
                numeric.append(number(value))
            except InputError:
                invalid += 1
        summaries[column] = {
            "missing": len(rows) - len(present),
            "present": len(present),
            "distinct": len(counts),
            "numeric_invalid": invalid,
            "numeric": numeric_summary(numeric) if numeric else None,
            "frequencies": [
                {"value": values_by_key[key], "count": count}
                for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
                    : config.frequency_limit
                ]
            ],
        }
    metrics = config.metrics or [Metric(op="count", name="row_count")]
    _, groups = aggregate(columns, rows, config.group_by, metrics)
    return {
        "row_count": len(rows),
        "column_count": len(columns),
        "columns": summaries,
        "groups": groups,
        "decimal_policy": "Exact Decimal totals; averages rounded to 28 significant digits",
    }
