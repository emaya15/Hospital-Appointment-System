from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, pagination_params, require_patient
from app.models.user import User
from app.schemas.common import Pagination
from app.schemas.rating import DoctorRatingsOut, RatingCreate, RatingOut
from app.services import rating_service

router = APIRouter(tags=["Ratings & Feedback"])


@router.post(
    "/appointments/{appointment_id}/rating",
    response_model=RatingOut,
    status_code=status.HTTP_201_CREATED,
)
def submit_rating(
    appointment_id: int,
    data: RatingCreate,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    """Rate the doctor (1-5) after a completed appointment. One rating per appointment."""
    return rating_service.submit_rating(db, user, appointment_id, data)


@router.get("/doctors/{doctor_id}/ratings", response_model=DoctorRatingsOut)
def doctor_ratings(
    doctor_id: int,
    _user: User = Depends(get_current_user),
    pagination: Pagination = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    return rating_service.get_doctor_ratings(db, doctor_id, pagination)
