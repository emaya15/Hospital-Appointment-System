from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.doctor import Doctor
from app.models.enums import AppointmentStatus
from app.models.mixins import TimestampMixin
from app.models.patient import Patient
from app.utils.clock import utcnow
from app.utils.db_types import UTCDateTime


class Appointment(TimestampMixin, Base):
    """A booked visit of one patient with one doctor.

    ``slot_active`` is 1 while the appointment occupies its slot and NULL once it is
    cancelled. The unique constraints include this column, so a cancelled appointment
    releases its slot (MySQL allows many NULLs in a unique index) while two live
    appointments can never share the same doctor/date/time.
    """

    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint("doctor_id", "appointment_date", "appointment_time", "slot_active", name="uq_doctor_slot"),
        UniqueConstraint(
            "patient_id", "doctor_id", "appointment_date", "slot_active", name="uq_patient_doctor_day"
        ),
        UniqueConstraint(
            "patient_id", "appointment_date", "appointment_time", "slot_active", name="uq_patient_slot"
        ),
        Index("ix_appointments_doctor_date", "doctor_id", "appointment_date"),
        Index("ix_appointments_patient_date", "patient_id", "appointment_date"),
        Index("ix_appointments_status_date", "status", "appointment_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_number: Mapped[str] = mapped_column(String(30), unique=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    appointment_date: Mapped[date] = mapped_column(Date)
    appointment_time: Mapped[time] = mapped_column(Time)
    token_number: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, native_enum=False, length=20), default=AppointmentStatus.BOOKED
    )
    consultation_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    reschedule_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    slot_active: Mapped[int | None] = mapped_column(nullable=True, default=1)
    cancellation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    patient: Mapped[Patient] = relationship()
    doctor: Mapped[Doctor] = relationship()
    history: Mapped[list["AppointmentHistory"]] = relationship(
        back_populates="appointment",
        cascade="all, delete-orphan",
        order_by="AppointmentHistory.id",
    )
    consultation: Mapped["Consultation"] = relationship(  # noqa: F821
        back_populates="appointment", uselist=False
    )
    files: Mapped[list["UploadedFile"]] = relationship(back_populates="appointment")  # noqa: F821
    rating: Mapped["Rating"] = relationship(back_populates="appointment", uselist=False)  # noqa: F821

    @property
    def patient_name(self) -> str:
        return self.patient.user.full_name

    @property
    def doctor_name(self) -> str:
        return self.doctor.user.full_name


class AppointmentHistory(Base):
    """Audit trail: one row for every status change (and every reschedule)."""

    __tablename__ = "appointment_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), index=True)
    old_status: Mapped[AppointmentStatus | None] = mapped_column(
        Enum(AppointmentStatus, native_enum=False, length=20), nullable=True
    )
    new_status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, native_enum=False, length=20)
    )
    changed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, server_default=func.now(), nullable=False
    )

    appointment: Mapped[Appointment] = relationship(back_populates="history")
