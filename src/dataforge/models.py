"""Normalized metadata. Large immutable data resides in separate artifacts."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, DateTime


def new_id() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_filename: Mapped[str]
    row_count: Mapped[int]
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="RESTRICT"), index=True
    )
    columns: Mapped[list["Column"]] = relationship(
        cascade="all, delete-orphan", order_by="Column.position"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(cascade="all, delete-orphan")


class Column(Base):
    __tablename__ = "columns"
    __table_args__ = (UniqueConstraint("dataset_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    name: Mapped[str]
    inferred_type: Mapped[str]
    missing_count: Mapped[int]


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("dataset_id", "kind"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str]
    path: Mapped[str] = mapped_column(unique=True)
    checksum: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int]


class ImportRecord(Base):
    __tablename__ = "imports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str]
    requested_name: Mapped[str]
    status: Mapped[str]
    error: Mapped[str | None]
    checksum: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Definition(Base):
    __tablename__ = "definitions"
    __table_args__ = (UniqueConstraint("kind", "name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(index=True)
    name: Mapped[str]
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ValidationRun(Base):
    __tablename__ = "validation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="RESTRICT"), index=True
    )
    definition_id: Mapped[str | None] = mapped_column(
        ForeignKey("definitions.id", ondelete="RESTRICT")
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    passed: Mapped[bool]
    issue_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    issues: Mapped[list["ValidationIssue"]] = relationship(
        cascade="all, delete-orphan", order_by="ValidationIssue.id"
    )


class ValidationIssue(Base):
    __tablename__ = "validation_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="CASCADE"), index=True
    )
    rule: Mapped[str]
    column: Mapped[str | None]
    row: Mapped[int]
    severity: Mapped[str]
    description: Mapped[str]


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    input_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="RESTRICT"), index=True
    )
    output_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id", ondelete="RESTRICT"))
    definition_id: Mapped[str | None] = mapped_column(
        ForeignKey("definitions.id", ondelete="RESTRICT")
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(index=True)
    error: Mapped[str | None]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="RESTRICT"), index=True
    )
    definition_id: Mapped[str | None] = mapped_column(
        ForeignKey("definitions.id", ondelete="RESTRICT")
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    output: Mapped["ReportOutput"] = relationship(cascade="all, delete-orphan")


class ReportOutput(Base):
    __tablename__ = "report_outputs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), unique=True
    )
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


Index("ix_definitions_kind_name", Definition.kind, Definition.name)
