from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.department import Department
from app.models.mixins import TimestampMixin
from app.models.user import User


class Doctor(TimestampMixin, Base):
    """Doctor profile attached to a DOCTOR user account."""

    __tablename__ = "doctors"
    __table_args__ = (
        CheckConstraint("experience_years >= 0", name="experience_non_negative"),
        CheckConstraint("consultation_fee > 0", name="fee_positive"),
        CheckConstraint("slot_duration_minutes IN (10, 15, 20, 30)", name="slot_duration_allowed"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    specialization: Mapped[str] = mapped_column(String(100))
    qualification: Mapped[str] = mapped_column(String(200))
    experience_years: Mapped[int] = mapped_column()
    consultation_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    slot_duration_minutes: Mapped[int] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    user: Mapped[User] = relationship()
    department: Mapped[Department] = relationship(back_populates="doctors")
    schedules: Mapped[list["DoctorSchedule"]] = relationship(  # noqa: F821
        back_populates="doctor", cascade="all, delete-orphan"
    )
    leaves: Mapped[list["DoctorLeave"]] = relationship(  # noqa: F821
        back_populates="doctor", cascade="all, delete-orphan"
    )

    @property
    def name(self) -> str:
        return self.user.full_name

    @property
    def email(self) -> str:
        return self.user.email

    @property
    def department_name(self) -> str:
        return self.department.name
