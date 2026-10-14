from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.appointment import Appointment
from app.models.mixins import TimestampMixin


class Consultation(TimestampMixin, Base):
    """What the doctor recorded during the visit (one per appointment)."""

    __tablename__ = "consultations"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)
    symptoms: Mapped[str] = mapped_column(Text)
    diagnosis: Mapped[str] = mapped_column(Text)
    advice: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    follow_up_reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    appointment: Mapped[Appointment] = relationship(back_populates="consultation")
    prescription: Mapped[list["PrescriptionItem"]] = relationship(
        back_populates="consultation",
        cascade="all, delete-orphan",
        order_by="PrescriptionItem.id",
    )


class PrescriptionItem(Base):
    """One medicine line of a prescription."""

    __tablename__ = "prescription_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"), index=True)
    medicine: Mapped[str] = mapped_column(String(150))
    dosage: Mapped[str] = mapped_column(String(100))
    duration: Mapped[str] = mapped_column(String(100))

    consultation: Mapped[Consultation] = relationship(back_populates="prescription")
