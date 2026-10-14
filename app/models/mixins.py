"""Reusable model mixins."""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from app.utils.clock import utcnow
from app.utils.db_types import UTCDateTime


class TimestampMixin:
    """Adds created_at / updated_at (stored in UTC)."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )
