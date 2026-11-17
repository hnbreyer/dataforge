"""Strict, versionable configurations shared by the CLI, API, and engines."""

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ColumnName = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Scalar = str | int | bool | None


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Rule(Schema):
    kind: Literal[
        "required",
        "numeric",
        "date",
        "range",
        "length",
        "allowed",
        "unique",
        "duplicate_rows",
        "compare",
    ]
    column: ColumnName | None = None
    severity: Literal["error", "warning"] = "error"
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    values: list[Scalar] | None = Field(default=None, max_length=10000)
    format: str = Field(default="%Y-%m-%d", max_length=100)
    other_column: ColumnName | None = None
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le"] = "eq"

    @model_validator(mode="after")
    def check(self):
        if self.kind != "duplicate_rows" and self.column is None:
            raise ValueError("This rule requires a column")
        if self.kind == "compare" and self.other_column is None:
            raise ValueError("compare requires other_column")
        if self.kind == "allowed" and self.values is None:
            raise ValueError("allowed requires values")
        if self.kind in {"range", "length"} and self.minimum is None and self.maximum is None:
            raise ValueError("range/length requires minimum or maximum")
        for limit in (self.minimum, self.maximum):
            if limit is not None and not limit.is_finite():
                raise ValueError("Bounds must be finite")
            if self.kind == "length" and limit is not None and (limit < 0 or limit != int(limit)):
                raise ValueError("Length bounds must be nonnegative integers")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        return self


class RuleSet(Schema):
    rules: list[Rule] = Field(min_length=1, max_length=100)


class Rename(Schema):
    op: Literal["rename"]
    mapping: dict[ColumnName, ColumnName] = Field(min_length=1)


class Select(Schema):
    op: Literal["select", "drop"]
    columns: list[ColumnName] = Field(min_length=1, max_length=1000)


class Filter(Schema):
    op: Literal["filter"]
    column: ColumnName
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le", "contains", "is_missing", "not_missing"]
    value: Scalar = None
    numeric: bool = False


class Sort(Schema):
    op: Literal["sort"]
    columns: list[ColumnName] = Field(min_length=1, max_length=1000)
    descending: bool = False
    numeric: bool = False


class Convert(Schema):
    op: Literal["convert"]
    column: ColumnName
    type: Literal["string", "integer", "decimal", "boolean", "date"]
    format: str = Field(default="%Y-%m-%d", max_length=100)
    on_error: Literal["fail", "null"] = "fail"


class Missing(Schema):
    op: Literal["missing"]
    columns: list[ColumnName] = Field(min_length=1, max_length=1000)
    strategy: Literal["fill", "drop"]
    value: Scalar = None


class Normalize(Schema):
    op: Literal["normalize"]
    columns: list[ColumnName] = Field(min_length=1, max_length=1000)
    mode: Literal["strip", "lower", "upper", "collapse"] = "strip"


class Deduplicate(Schema):
    op: Literal["deduplicate"]
    columns: list[ColumnName] | None = Field(default=None, min_length=1, max_length=1000)


class Calculate(Schema):
    op: Literal["calculate"]
    column: ColumnName
    expression: str = Field(min_length=1, max_length=500)


class Metric(Schema):
    op: Literal["count", "sum", "avg", "min", "max"]
    column: ColumnName | None = None
    name: ColumnName

    @model_validator(mode="after")
    def check(self):
        if self.op != "count" and self.column is None:
            raise ValueError("Numeric metrics require a column")
        return self


class Aggregate(Schema):
    op: Literal["aggregate"]
    group_by: list[ColumnName] = Field(default_factory=list, max_length=20)
    metrics: list[Metric] = Field(min_length=1, max_length=100)


Step = Annotated[
    Rename
    | Select
    | Filter
    | Sort
    | Convert
    | Missing
    | Normalize
    | Deduplicate
    | Calculate
    | Aggregate,
    Field(discriminator="op"),
]


class PipelineConfig(Schema):
    steps: list[Step] = Field(min_length=1, max_length=100)


class ReportConfig(Schema):
    group_by: list[ColumnName] = Field(default_factory=list, max_length=20)
    metrics: list[Metric] = Field(default_factory=list, max_length=100)
    frequency_limit: int = Field(default=20, ge=1, le=1000)


class DefinitionCreate(Schema):
    name: Name
    config: dict[str, Any]


class ValidationRequest(Schema):
    config: RuleSet | None = None
    definition: str | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.config is None) == (self.definition is None):
            raise ValueError("Provide exactly one of config or definition")
        return self


class PipelineRequest(Schema):
    dataset: str
    output_name: Name
    config: PipelineConfig | None = None
    definition: str | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.config is None) == (self.definition is None):
            raise ValueError("Provide exactly one of config or definition")
        return self


class ReportRequest(Schema):
    config: ReportConfig | None = None
    definition: str | None = None

    @model_validator(mode="after")
    def one(self):
        if self.config is not None and self.definition is not None:
            raise ValueError("Provide config or definition, not both")
        return self


class ColumnResponse(Schema):
    name: str
    position: int
    inferred_type: str
    missing_count: int


class DatasetResponse(Schema):
    id: str
    name: str
    source_filename: str
    row_count: int
    checksum: str
    created_at: str
    parent_id: str | None
    columns: list[ColumnResponse]


class Page(Schema):
    items: list[dict[str, Any]]
    total: int
    offset: int
    limit: int


class ValidationResponse(Schema):
    id: str
    dataset_id: str
    definition_id: str | None
    config: dict[str, Any]
    passed: bool
    issue_count: int
    created_at: str
    issues: Page | None = None


class JobResponse(Schema):
    id: str
    input_id: str
    output_id: str | None
    definition_id: str | None
    config: dict[str, Any]
    status: Literal["running", "succeeded", "failed"]
    error: str | None
    started_at: str
    finished_at: str | None


class ReportResponse(Schema):
    id: str
    dataset_id: str
    definition_id: str | None
    config: dict[str, Any]
    created_at: str
    result: dict[str, Any]


class DefinitionResponse(Schema):
    id: str
    kind: str
    name: str
    config: dict[str, Any]
    created_at: str


class PreviewResponse(Page):
    dataset_id: str
    columns: list[str]
