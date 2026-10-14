"""Pagination helpers (skip / limit)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.schemas.common import Pagination


def _count(db: Session, stmt: Select) -> int:
    return db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def paginate(db: Session, stmt: Select, pagination: Pagination):
    """Return (ORM objects, total) for a statement that selects one entity."""
    total = _count(db, stmt)
    items = db.scalars(stmt.offset(pagination.skip).limit(pagination.limit)).all()
    return items, total


def paginate_rows(db: Session, stmt: Select, pagination: Pagination):
    """Return (rows, total) for a statement that selects columns/aggregates."""
    total = _count(db, stmt)
    rows = db.execute(stmt.offset(pagination.skip).limit(pagination.limit)).all()
    return rows, total
