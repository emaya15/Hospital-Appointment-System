from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import MoneyOut

SlotDuration = Literal[10, 15, 20, 30]


class DoctorCreate(BaseModel):
    """Create a doctor profile for an existing DOCTOR user (see POST /auth/users)."""

    user_id: int
    department_id: int
    specialization: str = Field(min_length=2, max_length=100)
    qualification: str = Field(min_length=2, max_length=200)
    experience_years: int = Field(ge=0, le=70)
    consultation_fee: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    slot_duration_minutes: SlotDuration


class DoctorUpdate(BaseModel):
    department_id: int | None = None
    specialization: str | None = Field(default=None, min_length=2, max_length=100)
    qualification: str | None = Field(default=None, min_length=2, max_length=200)
    experience_years: int | None = Field(default=None, ge=0, le=70)
    consultation_fee: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    slot_duration_minutes: SlotDuration | None = None
    is_active: bool | None = None


class DoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    email: str
    department_id: int
    department_name: str
    specialization: str
    qualification: str
    experience_years: int
    consultation_fee: MoneyOut
    slot_duration_minutes: int
    is_active: bool
    created_at: datetime
