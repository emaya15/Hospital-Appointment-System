from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, pagination_params
from app.models.enums import FileCategory
from app.models.user import User
from app.schemas.common import Page, Pagination
from app.schemas.file import FileOut
from app.services import file_service

router = APIRouter(tags=["Files"])


@router.post(
    "/appointments/{appointment_id}/files",
    response_model=FileOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_file(
    appointment_id: int,
    file: UploadFile = File(..., description="PDF, JPG or PNG, maximum 5 MB"),
    category: FileCategory | None = Form(
        None, description="Patients: LAB_REPORT. Doctors: PRESCRIPTION (default) or SCAN"
    ),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a file. Returns 413 if larger than 5 MB and 415 for unsupported types."""
    return file_service.save_upload(db, user, appointment_id, file, category)


@router.get("/appointments/{appointment_id}/files", response_model=Page[FileOut])
def list_files(
    appointment_id: int,
    user: User = Depends(get_current_user),
    pagination: Pagination = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    items, total = file_service.list_files(db, user, appointment_id, pagination)
    return Page[FileOut](
        items=[FileOut.model_validate(i) for i in items],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/files/{file_id}/download")
def download_file(file_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record, path = file_service.get_file_for_download(db, user, file_id)
    return FileResponse(path, media_type=record.content_type, filename=record.original_filename)
