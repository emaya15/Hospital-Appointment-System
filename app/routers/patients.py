from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db, pagination_params, require_patient
from app.models.user import User
from app.schemas.common import Page, Pagination
from app.schemas.file import PatientHistoryItem
from app.services import appointment_service

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.get("/me/history", response_model=Page[PatientHistoryItem])
def my_history(
    user: User = Depends(require_patient),
    pagination: Pagination = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    """My past appointments with diagnosis and the files I am allowed to see."""
    items, total = appointment_service.patient_history(db, user, pagination)
    return Page[PatientHistoryItem](items=items, total=total, skip=pagination.skip, limit=pagination.limit)
