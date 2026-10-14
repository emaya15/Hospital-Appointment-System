from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_doctor
from app.models.user import User
from app.schemas.appointment import AppointmentOut
from app.services import queue_service

router = APIRouter(prefix="/doctors", tags=["Live Queue"])


@router.put("/me/call-next", response_model=AppointmentOut)
def call_next_patient(user: User = Depends(require_doctor), db: Session = Depends(get_db)):
    """Call the next checked-in patient (only after the current consultation is saved)."""
    return queue_service.call_next(db, user)
