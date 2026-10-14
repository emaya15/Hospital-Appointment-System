"""Doctor leave handling.

Creating a leave cancels the doctor's open appointments inside the leave period,
writes the history rows, e-mails the patients and refreshes the live queue.
"""

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.enums import AppointmentStatus
from app.models.schedule import DoctorLeave
from app.models.user import User
from app.schemas.common import Pagination
from app.schemas.schedule import LeaveCreate
from app.services import appointment_service, doctor_service, notification_service
from app.utils import clock
from app.utils.exceptions import BadRequestError, ConflictError
from app.utils.pagination import paginate
from app.websockets import events


def create_leave(
    db: Session,
    user: User,
    doctor_id: int,
    data: LeaveCreate,
    background_tasks: BackgroundTasks | None = None,
) -> tuple[DoctorLeave, int]:
    """Create a leave. Returns (leave, number of cancelled appointments)."""
    doctor = doctor_service.get_doctor_or_404(db, doctor_id)
    doctor_service.ensure_can_manage(user, doctor)

    if data.end_date < data.start_date:
        raise BadRequestError("end_date must not be earlier than start_date")
    if data.start_date < clock.today():
        raise BadRequestError("Leave cannot start in the past")

    overlapping = db.scalar(
        select(DoctorLeave.id)
        .where(
            DoctorLeave.doctor_id == doctor.id,
            DoctorLeave.start_date <= data.end_date,
            DoctorLeave.end_date >= data.start_date,
        )
        .limit(1)
    )
    if overlapping is not None:
        raise ConflictError("This leave overlaps with an existing leave")

    leave = DoctorLeave(
        doctor_id=doctor.id, start_date=data.start_date, end_date=data.end_date, reason=data.reason
    )
    db.add(leave)

    affected = db.scalars(
        select(Appointment)
        .where(
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date >= data.start_date,
            Appointment.appointment_date <= data.end_date,
            Appointment.status.in_([AppointmentStatus.BOOKED, AppointmentStatus.CHECKED_IN]),
        )
        .with_for_update()
    ).all()

    for appt in affected:
        appointment_service.cancel_appointment_core(db, appt, user.id, "Doctor is on leave")
    db.commit()

    # After the commit: e-mail patients, notify live clients, refresh the queue.
    for appt in affected:
        notification_service.appointment_cancelled(background_tasks, appt, doctor_leave=True)
    for day in {appt.appointment_date for appt in affected}:
        appointment_service.refresh_queue(doctor.id, day)
    if affected:
        events.notify_user(
            doctor.user_id,
            "leave_created",
            f"Leave saved. {len(affected)} appointment(s) were cancelled.",
        )
    return leave, len(affected)


def list_leaves(db: Session, doctor_id: int, pagination: Pagination):
    doctor_service.get_doctor_or_404(db, doctor_id)
    stmt = (
        select(DoctorLeave)
        .where(DoctorLeave.doctor_id == doctor_id)
        .order_by(DoctorLeave.start_date.desc(), DoctorLeave.id.desc())
    )
    return paginate(db, stmt, pagination)
