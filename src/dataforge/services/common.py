from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dataforge.errors import InputError


def parse_config(schema: type[BaseModel], value: dict | BaseModel):
    try:
        return schema.model_validate(value)
    except ValidationError as exc:
        raise InputError(str(exc)) from exc


def stamp(value: datetime | None) -> str | None:
    return value.replace(tzinfo=UTC).isoformat() if value is not None else None


def record(model: Any, exclude: set[str] | None = None) -> dict:
    result = {}
    for column in model.__table__.columns:
        if column.name in (exclude or set()):
            continue
        value = getattr(model, column.name)
        result[column.name] = stamp(value) if isinstance(value, datetime) else value
    return result


def page(
    session: Session,
    model,
    offset: int = 0,
    limit: int = 50,
    filters: tuple = (),
    ascending: bool = False,
) -> dict:
    if offset < 0 or not 1 <= limit <= 200:
        raise InputError("Pagination requires offset >= 0 and limit between 1 and 200")
    total = session.scalar(select(func.count()).select_from(model).where(*filters))
    # A stable secondary key makes page boundaries deterministic.
    sort = getattr(model, "created_at", getattr(model, "started_at", model.id))
    items = session.scalars(
        select(model)
        .where(*filters)
        .order_by(
            sort.asc() if ascending else sort.desc(),
            model.id.asc() if ascending else model.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [record(item) for item in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }
