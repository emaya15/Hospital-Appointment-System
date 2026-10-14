"""Time helpers.

Appointment dates/times are "wall clock" values in the hospital time zone
(settings.TIMEZONE). Every comparison is done with timezone-aware datetimes.
Audit timestamps (created_at, updated_at, ...) are stored in UTC.

Services call ``clock.now()`` (not ``datetime.now()``) so tests can freeze time.
"""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from app.config import settings

TZ = ZoneInfo(settings.TIMEZONE)


def now() -> datetime:
    """Current time in the hospital time zone (timezone-aware)."""
    return datetime.now(TZ)


def today() -> date:
    """Current date in the hospital time zone."""
    return now().date()


def utcnow() -> datetime:
    """Current time in UTC (timezone-aware). Used for audit timestamps."""
    return datetime.now(timezone.utc)


def slot_datetime(day: date, at: time) -> datetime:
    """Combine an appointment date and time into an aware datetime."""
    return datetime.combine(day, at.replace(tzinfo=None), tzinfo=TZ)
