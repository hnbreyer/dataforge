"""Canonical scalar and Decimal policies; never use binary float for amounts."""

import json
import operator
import re
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from dataforge.errors import InputError

Row = dict[str, Any]
COMPARISONS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "ge": operator.ge,
    "lt": operator.lt,
    "le": operator.le,
}
NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def missing(value: Any) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def number(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise InputError(f"Expected a number, got {value!r}")
    text = str(value).strip()
    if len(text) > 100 or not NUMBER.fullmatch(text):
        raise InputError(f"Invalid numeric value: {text[:80]!r}")
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise InputError("Invalid numeric value") from exc
    if not result.is_finite() or len(result.as_tuple().digits) > 38 or abs(result.adjusted()) > 38:
        raise InputError(
            "Numeric values must be finite, at most 38 significant digits, and exponent within ±38"
        )
    return result


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def stable(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def numeric_summary(values: list[Decimal]) -> dict:
    if not values:
        return {"count": 0, "sum": "0", "avg": None, "min": None, "max": None}
    with localcontext() as ctx:
        ctx.prec = 160
        total = sum(values, Decimal(0))
        # Averages have an explicit 28-significant-digit policy.
        with localcontext() as avg_ctx:
            avg_ctx.prec = 28
            average = total / len(values)
        return {
            "count": len(values),
            "sum": decimal_text(total),
            "avg": decimal_text(average),
            "min": decimal_text(min(values)),
            "max": decimal_text(max(values)),
        }
