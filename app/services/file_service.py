"""Secure file uploads and downloads.

Rules
-----
* Only PDF, JPG/JPEG and PNG (checked by extension, content type AND file signature).
* Maximum size is MAX_UPLOAD_MB (default 5 MB) -> HTTP 413.
* Disk names are random UUIDs; files are created with mode "xb" so nothing is overwritten.
* The original file name is kept only as database metadata (never used as a path).
* Patients upload LAB_REPORTs to their own appointments; doctors upload PRESCRIPTIONs and
  SCANs to appointments assigned to them. Admins cannot upload.
"""

import logging
import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.enums import AppointmentStatus, FileCategory, Role
from app.models.file import UploadedFile
from app.models.user import User
from app.schemas.common import Pagination
from app.services import appointment_service
from app.utils.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from app.utils.pagination import paginate

logger = logging.getLogger(__name__)

# extension -> (allowed content types, file signature)
ALLOWED_TYPES = {
    ".pdf": ({"application/pdf"}, b"%PDF"),
    ".jpg": ({"image/jpeg", "image/jpg"}, b"\xff\xd8\xff"),
    ".jpeg": ({"image/jpeg", "image/jpg"}, b"\xff\xd8\xff"),
    ".png": ({"image/png"}, b"\x89PNG\r\n\x1a\n"),
}
CHUNK_SIZE = 64 * 1024


def _resolve_category(user: User, requested: FileCategory | None) -> FileCategory:
    if user.role == Role.PATIENT:
        if requested not in (None, FileCategory.LAB_REPORT):
            raise ForbiddenError("Patients can upload lab reports only")
        return FileCategory.LAB_REPORT
    if user.role == Role.DOCTOR:
        category = requested or FileCategory.PRESCRIPTION
        if category not in (FileCategory.PRESCRIPTION, FileCategory.SCAN):
            raise ForbiddenError("Doctors can upload prescriptions and scans only")
        return category
    raise ForbiddenError("Administrators cannot upload medical files")


def _clean_original_name(name: str | None) -> str:
    base = os.path.basename((name or "file").replace("\\", "/")).strip()
    return (base or "file")[:255]


def save_upload(
    db: Session,
    user: User,
    appointment_id: int,
    upload: UploadFile,
    category: FileCategory | None = None,
) -> UploadedFile:
    appt = appointment_service.get_appointment_for_user(db, user, appointment_id)
    category = _resolve_category(user, category)

    if appt.status in (AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW):
        raise BadRequestError("Files cannot be added to a cancelled or no-show appointment")

    original_name = _clean_original_name(upload.filename)
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_TYPES:
        raise UnsupportedMediaTypeError("Only PDF, JPG and PNG files are allowed")
    allowed_content_types, signature = ALLOWED_TYPES[extension]
    content_type = (upload.content_type or "").lower()
    if content_type not in allowed_content_types:
        raise UnsupportedMediaTypeError("File content type does not match an allowed type (PDF, JPG, PNG)")

    stream = upload.file
    first_chunk = stream.read(CHUNK_SIZE)
    if not first_chunk.startswith(signature):
        raise UnsupportedMediaTypeError("File content does not match its extension")

    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    destination = settings.UPLOAD_DIR / stored_name

    size = 0
    try:
        with open(destination, "xb") as out:  # "x": fail instead of overwriting
            chunk = first_chunk
            while chunk:
                size += len(chunk)
                if size > settings.MAX_UPLOAD_BYTES:
                    raise PayloadTooLargeError(f"File is too large. Maximum size is {settings.MAX_UPLOAD_MB} MB")
                out.write(chunk)
                chunk = stream.read(CHUNK_SIZE)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    record = UploadedFile(
        appointment_id=appt.id,
        uploaded_by_user_id=user.id,
        category=category,
        original_filename=original_name,
        stored_filename=stored_name,
        content_type=content_type if content_type != "image/jpg" else "image/jpeg",
        size_bytes=size,
    )
    db.add(record)
    try:
        db.commit()
    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise
    return record


def list_files(db: Session, user: User, appointment_id: int, pagination: Pagination):
    appt = appointment_service.get_appointment_for_user(db, user, appointment_id)
    stmt = (
        select(UploadedFile)
        .where(UploadedFile.appointment_id == appt.id)
        .order_by(UploadedFile.created_at.desc(), UploadedFile.id.desc())
    )
    return paginate(db, stmt, pagination)


def get_file_for_download(db: Session, user: User, file_id: int) -> tuple[UploadedFile, Path]:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise NotFoundError("File not found")
    appointment_service.get_appointment_for_user(db, user, record.appointment_id)  # ownership check

    path = settings.UPLOAD_DIR / record.stored_filename
    if not path.is_file():
        logger.error("File %s is in the database but missing on disk", record.id)
        raise NotFoundError("File not found")
    return record, path
