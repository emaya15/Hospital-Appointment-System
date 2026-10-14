"""Import every model so SQLAlchemy / Alembic can see all tables."""

from app.models.appointment import Appointment, AppointmentHistory
from app.models.consultation import Consultation, PrescriptionItem
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.enums import AppointmentStatus, FileCategory, Role
from app.models.file import UploadedFile
from app.models.patient import Patient
from app.models.rating import Rating
from app.models.schedule import DoctorLeave, DoctorSchedule
from app.models.token import RefreshToken
from app.models.user import User

__all__ = [
    "Appointment",
    "AppointmentHistory",
    "AppointmentStatus",
    "Consultation",
    "Department",
    "Doctor",
    "DoctorLeave",
    "DoctorSchedule",
    "FileCategory",
    "Patient",
    "PrescriptionItem",
    "Rating",
    "RefreshToken",
    "Role",
    "UploadedFile",
    "User",
]
