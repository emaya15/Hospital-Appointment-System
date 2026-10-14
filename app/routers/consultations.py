from fastapi import APIRouter, BackgroundTasks, Depends, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_doctor
from app.models.user import User
from app.schemas.consultation import ConsultationCreate, ConsultationOut
from app.services import consultation_service, pdf_service

router = APIRouter(prefix="/appointments", tags=["Consultations & Prescriptions"])


@router.post(
    "/{appointment_id}/consultation",
    response_model=ConsultationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_consultation(
    appointment_id: int,
    data: ConsultationCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_doctor),
    db: Session = Depends(get_db),
):
    """Assigned doctor records the consultation. The appointment becomes COMPLETED."""
    return consultation_service.create_consultation(db, user, appointment_id, data, background_tasks)


@router.get("/{appointment_id}/consultation", response_model=ConsultationOut)
def get_consultation(
    appointment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return consultation_service.get_consultation(db, user, appointment_id)


@router.get(
    "/{appointment_id}/prescription-pdf",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}, "description": "Prescription PDF"}},
)
def download_prescription_pdf(
    appointment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Download the prescription as a PDF (patient owner, assigned doctor or admin)."""
    path = pdf_service.get_prescription_pdf(db, user, appointment_id)
    return FileResponse(path, media_type="application/pdf", filename=path.name)
