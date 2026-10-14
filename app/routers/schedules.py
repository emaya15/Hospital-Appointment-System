"""Doctor schedules, leaves and available slots."""

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, pagination_params, require_roles
from app.models.enums import Role
from app.models.user import User
from app.schemas.common import MessageOut, Page, Pagination
from app.schemas.schedule import (
    AvailableSlotsOut,
    LeaveCreate,
    LeaveCreatedOut,
    LeaveOut,
    ScheduleCreate,
    ScheduleOut,
    ScheduleUpdate,
)
from app.services import doctor_service, leave_service, schedule_service

router = APIRouter(tags=["Schedules & Leaves"])

doctor_or_admin = require_roles(Role.DOCTOR, Role.ADMIN)


@router.post("/doctors/{doctor_id}/schedules", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(
    doctor_id: int,
    data: ScheduleCreate,
    user: User = Depends(doctor_or_admin),
    db: Session = Depends(get_db),
):
    return schedule_service.create_schedule(db, user, doctor_id, data)


@router.get("/doctors/{doctor_id}/schedules", response_model=Page[ScheduleOut])
def list_schedules(
    doctor_id: int,
    _user: User = Depends(get_current_user),
    pagination: Pagination = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    items, total = schedule_service.list_schedules(db, doctor_id, pagination)
    return Page[ScheduleOut](
        items=[ScheduleOut.model_validate(i) for i in items],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.put("/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: int,
    data: ScheduleUpdate,
    user: User = Depends(doctor_or_admin),
    db: Session = Depends(get_db),
):
    return schedule_service.update_schedule(db, user, schedule_id, data)


@router.delete("/schedules/{schedule_id}", response_model=MessageOut)
def delete_schedule(schedule_id: int, user: User = Depends(doctor_or_admin), db: Session = Depends(get_db)):
    schedule_service.delete_schedule(db, user, schedule_id)
    return MessageOut(message="Schedule deleted")


@router.post("/doctors/{doctor_id}/leaves", response_model=LeaveCreatedOut, status_code=status.HTTP_201_CREATED)
def create_leave(
    doctor_id: int,
    data: LeaveCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(doctor_or_admin),
    db: Session = Depends(get_db),
):
    """Create a leave. Open appointments in the period are cancelled and patients are e-mailed."""
    leave, cancelled = leave_service.create_leave(db, user, doctor_id, data, background_tasks)
    out = LeaveCreatedOut.model_validate(leave)
    out.cancelled_appointments = cancelled
    return out


@router.get("/doctors/{doctor_id}/leaves", response_model=Page[LeaveOut])
def list_leaves(
    doctor_id: int,
    _user: User = Depends(get_current_user),
    pagination: Pagination = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    items, total = leave_service.list_leaves(db, doctor_id, pagination)
    return Page[LeaveOut](
        items=[LeaveOut.model_validate(i) for i in items],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/doctors/{doctor_id}/available-slots", response_model=AvailableSlotsOut)
def available_slots(
    doctor_id: int,
    date: date = Query(..., description="Day to check, format YYYY-MM-DD"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doctor = doctor_service.get_doctor_or_404(db, doctor_id, only_active=user.role != Role.ADMIN)
    slots = schedule_service.available_slots(db, doctor, date)
    return AvailableSlotsOut(
        doctor_id=doctor.id,
        date=date,
        slot_duration_minutes=doctor.slot_duration_minutes,
        slots=[slot.strftime("%H:%M") for slot in slots],
    )
