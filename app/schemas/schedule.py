from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreate(BaseModel):
    """Working hours for one weekday. day_of_week: Monday=0 ... Sunday=6."""

    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    break_start: time | None = None
    break_end: time | None = None


class ScheduleUpdate(BaseModel):
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    break_start: time | None = None
    break_end: time | None = None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    day_of_week: int
    start_time: time
    end_time: time
    break_start: time | None
    break_end: time | None


class LeaveCreate(BaseModel):
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=255)


class LeaveOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    start_date: date
    end_date: date
    reason: str | None
    created_at: datetime


class LeaveCreatedOut(LeaveOut):
    cancelled_appointments: int = 0


class AvailableSlotsOut(BaseModel):
    doctor_id: int
    date: date
    slot_duration_minutes: int
    slots: list[str] = Field(description="Free slot start times as HH:MM")
