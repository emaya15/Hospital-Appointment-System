"""Enumerations used by the models and schemas."""

import enum


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"


class AppointmentStatus(str, enum.Enum):
    """Lifecycle: BOOKED -> CHECKED_IN -> IN_CONSULTATION -> COMPLETED.

    An appointment can also end as CANCELLED or NO_SHOW.
    """

    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    IN_CONSULTATION = "IN_CONSULTATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class FileCategory(str, enum.Enum):
    LAB_REPORT = "LAB_REPORT"
    PRESCRIPTION = "PRESCRIPTION"
    SCAN = "SCAN"


# Appointments that are still "pending" (not finished or cancelled)
OPEN_STATUSES = (
    AppointmentStatus.BOOKED,
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.IN_CONSULTATION,
)
