"""Doctor ratings and feedback (bonus feature)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import AppointmentStatus, Role
from app.models.rating import Rating
from app.models.user import User
from app.schemas.common import Pagination
from app.schemas.rating import DoctorRatingsOut, RatingCreate, RatingOut
from app.services import appointment_service, doctor_service
from app.utils.db import commit_or_conflict
from app.utils.exceptions import BadRequestError, ConflictError, ForbiddenError
from app.utils.pagination import paginate


def submit_rating(db: Session, user: User, appointment_id: int, data: RatingCreate) -> Rating:
    appt = appointment_service.get_appointment(db, appointment_id, lock=True)

    if user.role != Role.PATIENT or appt.patient.user_id != user.id:
        raise ForbiddenError("You can rate only your own completed appointments")
    if appt.status != AppointmentStatus.COMPLETED:
        raise BadRequestError("You can rate a doctor only after the appointment is completed")
    if db.scalar(select(Rating.id).where(Rating.appointment_id == appt.id)) is not None:
        raise ConflictError("You have already rated this appointment")

    rating = Rating(
        appointment_id=appt.id,
        patient_id=appt.patient_id,
        doctor_id=appt.doctor_id,
        rating=data.rating,
        review=data.review.strip() if data.review else None,
    )
    db.add(rating)
    commit_or_conflict(db, "You have already rated this appointment")
    return rating


def get_doctor_ratings(db: Session, doctor_id: int, pagination: Pagination) -> DoctorRatingsOut:
    doctor_service.get_doctor_or_404(db, doctor_id)

    average, total = db.execute(
        select(func.coalesce(func.avg(Rating.rating), 0), func.count(Rating.id)).where(
            Rating.doctor_id == doctor_id
        )
    ).one()

    stmt = select(Rating).where(Rating.doctor_id == doctor_id).order_by(Rating.created_at.desc(), Rating.id.desc())
    items, _ = paginate(db, stmt, pagination)

    return DoctorRatingsOut(
        doctor_id=doctor_id,
        average_rating=round(float(average), 2),
        total_ratings=int(total),
        skip=pagination.skip,
        limit=pagination.limit,
        ratings=[RatingOut.model_validate(r) for r in items],
    )
