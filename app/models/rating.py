from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.appointment import Appointment
from app.models.mixins import TimestampMixin


class Rating(TimestampMixin, Base):
    """A patient's rating of a doctor. Only one rating per appointment."""

    __tablename__ = "ratings"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    rating: Mapped[int] = mapped_column()
    review: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    appointment: Mapped[Appointment] = relationship(back_populates="rating")
