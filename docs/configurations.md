# Configuration reference

All configurations are strict JSON objects. Unknown fields, unknown operations,
wrong parameter types, invalid bounds, and missing required parameters are
rejected. Save one through `dataforge definition save KIND NAME FILE`, API
`POST /api/v1/definitions/KIND`, or the Definitions dashboard page. Definitions
are immutable: create a new name to revise one. Executions store full snapshots.

## Validation

A rule set has `rules` (1–100 objects). Each rule has `kind`, optional `severity`
(`error` by default, or `warning`), and the following parameters:

| Kind | Parameters | Behavior |
|---|---|---|
| `required` | `column` | Null, empty, or whitespace-only values fail |
| `numeric` | `column` | Require a supported finite Decimal value |
| `date` | `column`, `format` (default `%Y-%m-%d`) | Parse with `datetime.strptime` |
| `range` | `column`, `minimum` and/or `maximum` | Inclusive Decimal bounds |
| `length` | `column`, `minimum` and/or `maximum` | Inclusive nonnegative integer bounds, Unicode code points |
| `allowed` | `column`, `values` | Scalar membership, with typed equality |
| `unique` | `column` | Every repeat after the first value is an issue |
| `duplicate_rows` | none | Every identical full record after the first is an issue |
| `compare` | `column`, `other_column`, `operator` | Compare two columns |

Comparison operators are `eq`, `ne`, `gt`, `ge`, `lt`, `le`. Both numeric operands
use Decimal; other operands compare as strings. A missing comparison operand
produces an issue if the primary operand is present. Field rules other than
`required` skip missing primary values; combine a required rule when needed.
Uniqueness excludes missing values. Row duplicates include missing values.

```json
{
  "rules": [
    {"kind":"required","column":"amount"},
    {"kind":"range","column":"amount","minimum":"0","maximum":"100000"},
    {"kind":"allowed","column":"status","values":["paid","pending"]},
    {"kind":"compare","column":"start","other_column":"end","operator":"le"},
    {"kind":"unique","column":"id","severity":"warning"}
  ]
}
```

The result has a dataset reference, pass/fail summary, configuration snapshot,
and issue count. Retrieve paginated issues using the returned run UUID. Issues
are ordered by rule, then ascending data record. Warnings do not fail a run.
Repeated validation of the same input/config produces identical issues; UUIDs
and execution timestamps naturally differ.

## Pipelines

A pipeline has `steps` (1–100 objects). The complete evolving column schema and
expression syntax are validated **before** row processing. Runtime value errors
fail the job and roll back all output. Every successful run produces a new,
uniquely named dataset; the original remains unchanged.

| Operation | Required fields | Optional fields / policy |
|---|---|---|
| `rename` | `mapping`: old-to-new names | Applied simultaneously; collisions rejected; swaps allowed |
| `select` | `columns` | Defines output column order; unknown/duplicate columns rejected |
| `drop` | `columns` | Must leave at least one column |
| `filter` | `column`, `operator` | `value`, `numeric: false` |
| `sort` | `columns` | `descending: false`, `numeric: false`; missing keys always last; stable order |
| `convert` | `column`, `type` | `on_error: "fail"`, `format: "%Y-%m-%d"` |
| `missing` | `columns`, `strategy` | `strategy` is `fill` or `drop`; fill `value` defaults to null |
| `normalize` | `columns` | `mode`: `strip` (default), `lower`, `upper`, or `collapse` |
| `deduplicate` | none | `columns` optionally select a key; first occurrence retained |
| `calculate` | new `column`, `expression` | Cannot overwrite a column; use rename/drop explicitly |
| `aggregate` | `metrics` | `group_by: []`; replaces dataset with groups |

Filters support `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `contains`, `is_missing`, and
`not_missing`. Set `numeric: true` for numeric comparisons of imported strings;
otherwise operands compare in their stored scalar types. Ordering incomparable
types fails. For comparisons against missing operands, `eq` matches two missing
values and `ne` matches exactly one; ordered comparisons/contains return false.
Filters run explicitly and can remove all rows without removing column metadata.

Conversion types: `string`, `integer`, `decimal`, `boolean`, and `date`. Fractional
numbers cannot be converted to integers silently. Boolean conversion accepts
true/false/1/0, ignoring letter case. Date conversion returns an ISO date. Nulls
remain null. Set `on_error: "null"` explicitly to replace invalid values with null;
otherwise one invalid value fails the entire pipeline. Normalize operates on
string representations of present values and preserves nulls. `missing` with
`strategy: "drop"` removes records missing **any** specified field.

### Arithmetic expressions

Supported syntax: known column identifiers, decimal numeric literals, parentheses,
addition, subtraction, multiplication, division, and unary signs. For example:

```json
{"op":"calculate","column":"net","expression":"amount * quantity - discount"}
```

Names must be Python-style identifiers present in the current schema. Rename
columns containing spaces/punctuation before referring to them. Expressions have
at most 500 characters and 64 syntax nodes. Calls, imports, attributes, indexing,
comprehensions, strings, booleans, powers, floor division, and arbitrary Python
are rejected by an AST whitelist and interpreter. No code is compiled or executed.
Missing/non-numeric operands and division by zero fail the job. Division rounds
to 28 significant digits; other arithmetic uses 160-digit working precision and
rejects results outside the documented supported numeric bounds.

### Grouping and metrics

```json
{
  "steps": [{
    "op":"aggregate",
    "group_by":["category"],
    "metrics":[
      {"op":"count","name":"records"},
      {"op":"sum","column":"amount","name":"total"},
      {"op":"avg","column":"amount","name":"average"},
      {"op":"min","column":"amount","name":"minimum"},
      {"op":"max","column":"amount","name":"maximum"}
    ]
  }]
}
```

Metric names and group columns must be unique. Count without a column counts
records; count with a column counts nonmissing values. Numeric metrics exclude
missing values but reject nonnumeric present values. Empty numeric groups have
sum `"0"`, and null average/min/max. No grouping columns produces one global
group, including on an empty dataset. Groups have deterministic canonical-key
order; null is a valid grouping key. Grouping distinguishes boolean, integer,
and string values. Aggregate output includes grouping columns plus metric names.

## Reports

A report configuration has optional `group_by`, `metrics` (the same metric format
as aggregation), and `frequency_limit` (default 20, range 1–1000). `{}` profiles
the entire dataset and supplies one row-count summary. Grouping without metrics
produces row counts per group. At most 20 grouping columns and 100 metrics are
accepted.

Every report includes row/column counts and, per column: missing/present counts,
distinct counts, nonnumeric counts, exact numeric totals, averages, minimum,
maximum, and category frequencies. Numeric profiling excludes invalid values and
reports `numeric_invalid`; it does not pretend the whole column is numeric.
Explicit grouped numeric metrics reject invalid values. Category frequencies are
ordered by descending count and canonical value for ties, bounded by the requested
limit; other profile statistics inspect all records. The full report result is
persisted and exported as JSON. CSV export contains only its grouped summary.
