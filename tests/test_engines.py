from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from dataforge.config import Settings
from dataforge.engines.expressions import Expression
from dataforge.engines.parsing import infer_type, parse_data
from dataforge.engines.transformation import transform
from dataforge.engines.validation import validate_rows
from dataforge.engines.values import number
from dataforge.errors import InputError
from dataforge.schemas import PipelineConfig, RuleSet


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([None, " "], "unknown"),
        (["1", "2"], "integer"),
        (["1.20", "2"], "decimal"),
        ([True, "false"], "boolean"),
        (["2026-01-01"], "date"),
        (["1", "oops"], "string"),
    ],
)
def test_inference(values, expected):
    assert infer_type(values) == expected


@pytest.mark.parametrize(
    "value", [True, None, "NaN", "Infinity", "1e999", "1,000", "1_000", "9" * 101]
)
def test_numeric_rejections(value):
    with pytest.raises(InputError):
        number(value)


@pytest.mark.parametrize(
    ("data", "filename"),
    [
        (b"", "x.csv"),
        (b"a,a\n1,2", "x.csv"),
        (b"a,b\n1", "x.csv"),
        (b'a\n"open', "x.csv"),
        (b"a\n\xff", "x.csv"),
        (b"a\n\x00", "x.csv"),
        (b"[]", "x.json"),
        (b"{}", "x.json"),
        (b"[1]", "x.json"),
        (b'[{"a": []}]', "x.json"),
        (b'[{"a": 1, "a": 2}]', "x.json"),
        (b'[{"a": NaN}]', "x.json"),
        (b"a", "x.exe"),
    ],
)
def test_malformed_rejected(data, filename):
    with pytest.raises(InputError):
        parse_data(data, filename, Settings())


def test_missing_union_and_decimal_json():
    columns, rows = parse_data(b'[{"a":0.10},{"b":true}]', "x.json", Settings())
    assert columns == ["a", "b"]
    assert rows == [{"a": "0.10", "b": None}, {"a": None, "b": True}]


def test_csv_quotes_bom_and_blank_cells():
    _, rows = parse_data(
        '\ufeffa,b\r\n"hello, world","a\nb"\r\n ,\r\n'.encode(), "x.csv", Settings()
    )
    assert rows == [{"a": "hello, world", "b": "a\nb"}, {"a": None, "b": None}]


@pytest.mark.parametrize(
    "settings", [Settings(max_rows=1), Settings(max_file_bytes=2), Settings(max_cells=1)]
)
def test_import_limits(settings):
    with pytest.raises(InputError):
        parse_data(b"a,b\n1,2\n3,4", "x.csv", settings)


@pytest.mark.parametrize(
    ("kind", "extra", "values", "count"),
    [
        ("required", {}, [None, "", "x"], 2),
        ("numeric", {}, ["1", "oops", None], 1),
        ("date", {}, ["2026-01-01", "bad"], 1),
        ("range", {"minimum": 2, "maximum": 4}, ["1", "3", "5", "bad"], 3),
        ("length", {"minimum": 2, "maximum": 3}, ["a", "ab", "abcd"], 2),
        ("allowed", {"values": ["a"]}, ["a", "b", None], 1),
        ("unique", {}, ["a", "a", None, None], 1),
    ],
)
def test_validation_rules(kind, extra, values, count):
    rows = [{"v": value} for value in values]
    before = deepcopy(rows)
    config = RuleSet(rules=[{"kind": kind, "column": "v", **extra}])
    issues = validate_rows(["v"], rows, config)
    assert len(issues) == count
    assert rows == before
    assert issues == validate_rows(["v"], rows, config)


def test_duplicate_and_comparison_rules():
    config = RuleSet(
        rules=[
            {"kind": "duplicate_rows"},
            {"kind": "compare", "column": "a", "other_column": "b", "operator": "le"},
        ]
    )
    issues = validate_rows(
        ["a", "b"], [{"a": "1", "b": "2"}, {"a": "1", "b": "2"}, {"a": "3", "b": "2"}], config
    )
    assert [i["row"] for i in issues] == [2, 3]


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "range", "column": "x"},
        {"kind": "required"},
        {"kind": "compare", "column": "x"},
        {"kind": "allowed", "column": "x"},
        {"kind": "length", "column": "x", "minimum": -1},
        {"kind": "range", "column": "x", "minimum": 4, "maximum": 1},
    ],
)
def test_invalid_rules(rule):
    with pytest.raises(ValidationError):
        RuleSet(rules=[rule])


@pytest.mark.parametrize(
    "expression",
    [
        '__import__("os")',
        "a.__class__",
        "a[0]",
        "a ** 100",
        "[a]",
        "True",
        '"a"',
        "unknown + 1",
        "a // 2",
        "lambda: 1",
    ],
)
def test_expression_safety(expression):
    with pytest.raises(InputError):
        Expression(expression, ["a"])


def test_decimal_expression_and_zero_division():
    assert Expression("a + 0.2", ["a"]).evaluate({"a": "0.1"}) == "0.3"
    with pytest.raises(InputError):
        Expression("a / 0", ["a"]).evaluate({"a": "1"})


def test_all_transformations_and_input_preservation():
    rows = [{"a": "  X  ", "b": "2"}, {"a": "Y", "b": None}, {"a": "  X  ", "b": "2"}]
    before = deepcopy(rows)
    steps = [
        {"op": "rename", "mapping": {"a": "category"}},
        {"op": "normalize", "columns": ["category"], "mode": "strip"},
        {"op": "normalize", "columns": ["category"], "mode": "lower"},
        {"op": "missing", "columns": ["b"], "strategy": "fill", "value": "1"},
        {"op": "convert", "column": "b", "type": "integer"},
        {"op": "deduplicate"},
        {"op": "calculate", "column": "total", "expression": "b * 0.1"},
        {"op": "filter", "column": "total", "operator": "ge", "value": "0.2", "numeric": True},
        {"op": "sort", "columns": ["total"], "numeric": True},
        {"op": "select", "columns": ["category", "total"]},
    ]
    columns, result = transform(["a", "b"], rows, PipelineConfig(steps=steps), Settings())
    assert columns == ["category", "total"]
    assert result == [{"category": "x", "total": "0.2"}]
    assert rows == before


def test_aggregation_exact_decimal():
    _, rows = transform(
        ["a", "b"],
        [{"a": "x", "b": "0.1"}, {"a": "x", "b": "0.2"}],
        PipelineConfig(
            steps=[
                {
                    "op": "aggregate",
                    "group_by": ["a"],
                    "metrics": [{"op": "sum", "column": "b", "name": "total"}],
                }
            ]
        ),
        Settings(),
    )
    assert Decimal(rows[0]["total"]) == Decimal("0.3")


@pytest.mark.parametrize(
    "step",
    [
        {"op": "rename", "mapping": {"a": "b"}},
        {"op": "drop", "columns": ["a", "b"]},
        {"op": "select", "columns": ["missing"]},
        {"op": "calculate", "column": "a", "expression": "1"},
    ],
)
def test_bad_pipeline_schema(step):
    with pytest.raises(InputError):
        transform(["a", "b"], [], PipelineConfig(steps=[step]), Settings())


@pytest.mark.parametrize(
    ("target", "value", "expected"),
    [
        ("integer", "2.0", 2),
        ("decimal", "0.10", "0.10"),
        ("boolean", "TRUE", True),
        ("boolean", "0", False),
        ("date", "2026-01-03", "2026-01-03"),
        ("string", True, "True"),
    ],
)
def test_conversions(target, value, expected):
    config = PipelineConfig(steps=[{"op": "convert", "column": "v", "type": target}])
    _, rows = transform(["v"], [{"v": value}], config, Settings())
    assert rows == [{"v": expected}]


@pytest.mark.parametrize(
    ("target", "value"),
    [("integer", "2.5"), ("date", "2026-02-30"), ("boolean", "yes"), ("decimal", "oops")],
)
def test_conversion_fail_or_explicit_null(target, value):
    step = {"op": "convert", "column": "v", "type": target}
    with pytest.raises(InputError):
        transform(["v"], [{"v": value}], PipelineConfig(steps=[step]), Settings())
    _, rows = transform(
        ["v"], [{"v": value}], PipelineConfig(steps=[{**step, "on_error": "null"}]), Settings()
    )
    assert rows == [{"v": None}]


@pytest.mark.parametrize("descending", [True, False])
def test_sort_missing_last_and_numeric_order(descending):
    config = PipelineConfig(
        steps=[{"op": "sort", "columns": ["v"], "numeric": True, "descending": descending}]
    )
    _, rows = transform(["v"], [{"v": "10"}, {"v": None}, {"v": "2"}], config, Settings())
    assert [r["v"] for r in rows] == (["10", "2", None] if descending else ["2", "10", None])


def test_aggregate_all_metrics_and_missing_values():
    config = PipelineConfig(
        steps=[
            {
                "op": "aggregate",
                "metrics": [
                    {"op": "count", "name": "rows"},
                    {"op": "count", "column": "v", "name": "present"},
                    {"op": "avg", "column": "v", "name": "average"},
                    {"op": "min", "column": "v", "name": "minimum"},
                    {"op": "max", "column": "v", "name": "maximum"},
                ],
            }
        ]
    )
    _, rows = transform(["v"], [{"v": "0.1"}, {"v": None}, {"v": "0.2"}], config, Settings())
    assert rows == [
        {"rows": 3, "present": 2, "average": "0.15", "minimum": "0.1", "maximum": "0.2"}
    ]


def test_all_steps_planned_before_data_execution():
    config = PipelineConfig(
        steps=[
            {"op": "calculate", "column": "x", "expression": "v / 0"},
            {"op": "drop", "columns": ["unknown"]},
        ]
    )
    with pytest.raises(InputError, match="Step 2"):
        transform(["v"], [{"v": "1"}], config, Settings())


def test_expression_division_uses_documented_precision():
    result = Expression("a / 3", ["a"]).evaluate({"a": "1"})
    assert result == "0." + "3" * 28


def test_simultaneous_rename_swap_and_drop():
    config = PipelineConfig(
        steps=[{"op": "rename", "mapping": {"a": "b", "b": "a"}}, {"op": "drop", "columns": ["b"]}]
    )
    assert transform(["a", "b"], [{"a": "one", "b": "two"}], config, Settings()) == (
        ["a"],
        [{"a": "two"}],
    )


@pytest.mark.parametrize(("mode", "expected"), [("upper", "  A   B  "), ("collapse", "a b")])
def test_string_normalization_modes(mode, expected):
    config = PipelineConfig(steps=[{"op": "normalize", "columns": ["v"], "mode": mode}])
    assert transform(["v"], [{"v": "  a   b  "}], config, Settings())[1][0]["v"] == expected


def test_extreme_decimal_total_has_no_context_rounding():
    from dataforge.engines.values import numeric_summary

    large = number("9e38")
    small = number("0." + "0" * 37 + "12345678901234567890123456789012345678")
    result = numeric_summary([large, small])["sum"]
    assert (
        result
        == "900000000000000000000000000000000000000."
        + "0" * 37
        + "12345678901234567890123456789012345678"
    )
