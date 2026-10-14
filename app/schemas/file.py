from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict

from app.models.enums import AppointmentStatus, FileCategory
from app.schemas.consultation import PrescriptionItemOut


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    category: FileCategory
    original_filename: str
    content_type: str
    size_bytes: int
    uploaded_by_user_id: int
    created_at: datetime


class HistoryConsultationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symptoms: str
    diagnosis: str
    prescription: list[PrescriptionItemOut]
    advice: str | None
    follow_up_date: date | None


class PatientHistoryItem(BaseModel):
    """One past/current appointment with its diagnosis and authorized files."""

    model_config = ConfigDict(from_attributes=True)

    appointment_id: int
    appointment_number: str
    appointment_date: date
    appointment_time: time
    status: AppointmentStatus
    doctor_id: int
    doctor_name: str
    reason: str
    consultation: HistoryConsultationOut | None = None
    files: list[FileOut] = []
