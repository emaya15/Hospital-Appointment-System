from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PrescriptionItemIn(BaseModel):
    medicine: str = Field(min_length=1, max_length=150)
    dosage: str = Field(min_length=1, max_length=100)
    duration: str = Field(min_length=1, max_length=100)


class PrescriptionItemOut(PrescriptionItemIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ConsultationCreate(BaseModel):
    symptoms: str = Field(min_length=2)
    diagnosis: str = Field(min_length=2)
    prescription: list[PrescriptionItemIn] = Field(default_factory=list)
    advice: str | None = None
    follow_up_date: date | None = None


class ConsultationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    symptoms: str
    diagnosis: str
    prescription: list[PrescriptionItemOut]
    advice: str | None
    follow_up_date: date | None
    created_at: datetime
