from datetime import date, time

from sqlalchemy import Date, ForeignKey, Index, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.doctor import Doctor
from app.models.mixins import TimestampMixin


class DoctorSchedule(TimestampMixin, Base):
    """Weekly working hours of a doctor (day_of_week: Monday=0 ... Sunday=6)."""

    __tablename__ = "doctor_schedules"
    __table_args__ = (Index("ix_doctor_schedules_doctor_day", "doctor_id", "day_of_week"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    day_of_week: Mapped[int] = mapped_column()
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    break_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    break_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    doctor: Mapped[Doctor] = relationship(back_populates="schedules")


class DoctorLeave(TimestampMixin, Base):
    """A leave period (inclusive dates) during which the doctor is unavailable."""

    __tablename__ = "doctor_leaves"
    __table_args__ = (Index("ix_doctor_leaves_doctor_dates", "doctor_id", "start_date", "end_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    doctor: Mapped[Doctor] = relationship(back_populates="leaves")
