from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AppointmentStatus
from app.schemas.common import MoneyOut


class AppointmentCreate(BaseModel):
    doctor_id: int
    appointment_date: date
    appointment_time: time
    reason: str = Field(min_length=3, max_length=500)


class RescheduleRequest(BaseModel):
    new_date: date
    new_time: time


class CancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_number: str
    patient_id: int
    patient_name: str
    doctor_id: int
    doctor_name: str
    appointment_date: date
    appointment_time: time
    token_number: int
    reason: str
    status: AppointmentStatus
    consultation_fee: MoneyOut
    reschedule_count: int
    created_at: datetime


class AppointmentHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    old_status: AppointmentStatus | None
    new_status: AppointmentStatus
    changed_by_user_id: int | None
    note: str | None
    changed_at: datetime


class AppointmentDetailOut(AppointmentOut):
    history: list[AppointmentHistoryOut] = []
