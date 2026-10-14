"""Custom SQLAlchemy column types."""

from datetime import timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """DateTime stored as naive UTC in the database, returned as aware UTC.

    MySQL has no time-zone aware DATETIME, so we normalise everything to UTC
    when saving and attach the UTC tzinfo again when loading.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value  # naive values are assumed to already be UTC
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)
