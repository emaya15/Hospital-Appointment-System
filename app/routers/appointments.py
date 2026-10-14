from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.dependencies import (
    get_current_user,
    get_db,
    pagination_params,
    require_admin,
    require_patient,
    require_roles,
)
from app.models.enums import AppointmentStatus, Role
from app.models.user import User
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentDetailOut,
    AppointmentOut,
    CancelRequest,
    RescheduleRequest,
)
from app.schemas.common import Page, Pagination
from app.services import appointment_service

router = APIRouter(prefix="/appointments", tags=["Appointments"])

patient_or_admin = require_roles(Role.PATIENT, Role.ADMIN)


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def book_appointment(
    data: AppointmentCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_patient),
    db: Session = Depends(get_db),
):
    """Book a slot (patients only). Returns 409 if the slot or the patient is already booked."""
    return appointment_service.book_appointment(db, user, data, background_tasks)


@router.get("", response_model=Page[AppointmentOut])
def list_appointments(
    status_filter: AppointmentStatus | None = Query(None, alias="status"),
    doctor_id: int | None = Query(None),
    date_from: date | None = Query(None, description="YYYY-MM-DD"),
    date_to: date | None = Query(None, description="YYYY-MM-DD"),
    appointment_number: str | None = Query(None, description="Full or partial, e.g. APT-20261020"),
    user: User = Depends(get_current_user),
    pagination: Pagination = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    """Patients see their own appointments, doctors their own schedule, admins everything."""
    items, total = appointment_service.list_appointments(
        db,
        user,
        pagination,
        status=status_filter,
        doctor_id=doctor_id,
        date_from=date_from,
        date_to=date_to,
        appointment_number=appointment_number,
    )
    return Page[AppointmentOut](
        items=[AppointmentOut.model_validate(i) for i in items],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/{appointment_id}", response_model=AppointmentDetailOut)
def get_appointment(
    appointment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return appointment_service.get_appointment_for_user(db, user, appointment_id)


@router.put("/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule_appointment(
    appointment_id: int,
    data: RescheduleRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(patient_or_admin),
    db: Session = Depends(get_db),
):
    return appointment_service.reschedule_appointment(db, user, appointment_id, data, background_tasks)


@router.put("/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel_appointment(
    appointment_id: int,
    background_tasks: BackgroundTasks,
    data: CancelRequest | None = None,
    user: User = Depends(patient_or_admin),
    db: Session = Depends(get_db),
):
    reason = data.reason if data else None
    return appointment_service.cancel_appointment(db, user, appointment_id, reason, background_tasks)


@router.put("/{appointment_id}/check-in", response_model=AppointmentOut)
def check_in(
    appointment_id: int,
    user: User = Depends(patient_or_admin),
    db: Session = Depends(get_db),
):
    """Check in from 30 minutes before the slot (reception/admin, or the patient themselves)."""
    return appointment_service.check_in(db, user, appointment_id)
