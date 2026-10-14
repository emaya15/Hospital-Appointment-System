"""Appointment booking, rescheduling, cancellation, check-in and no-show logic.

Double booking is prevented in two layers:
1. the doctor row is locked (``SELECT ... FOR UPDATE``) while a booking is validated and saved
2. unique constraints in the database (see models/appointment.py) reject any duplicate slot
"""

import logging
from datetime import date, time, timedelta

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.appointment import Appointment, AppointmentHistory
from app.models.doctor import Doctor
from app.models.enums import AppointmentStatus, Role
from app.models.patient import Patient
from app.models.user import User
from app.schemas.appointment import AppointmentCreate, RescheduleRequest
from app.schemas.common import Pagination
from app.schemas.file import FileOut, HistoryConsultationOut, PatientHistoryItem
from app.services import notification_service, schedule_service
from app.utils import clock
from app.utils.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.utils.pagination import paginate
from app.websockets import events

logger = logging.getLogger(__name__)

S = AppointmentStatus

# Allowed status changes. Anything else is rejected.
ALLOWED_TRANSITIONS: dict[AppointmentStatus, set[AppointmentStatus]] = {
    S.BOOKED: {S.CHECKED_IN, S.CANCELLED, S.NO_SHOW},
    S.CHECKED_IN: {S.IN_CONSULTATION, S.CANCELLED},
    S.IN_CONSULTATION: {S.COMPLETED},
    S.COMPLETED: set(),
    S.CANCELLED: set(),
    S.NO_SHOW: set(),
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _normalise(at: time) -> time:
    return at.replace(second=0, microsecond=0, tzinfo=None)


def get_appointment(db: Session, appointment_id: int, *, lock: bool = False) -> Appointment:
    stmt = select(Appointment).where(Appointment.id == appointment_id)
    if lock:
        stmt = stmt.with_for_update()
    appt = db.scalar(stmt)
    if appt is None:
        raise NotFoundError("Appointment not found")
    return appt


def ensure_can_view(user: User, appt: Appointment) -> None:
    """Admin: any. Patient: own appointments. Doctor: appointments assigned to them."""
    if user.role == Role.ADMIN:
        return
    if user.role == Role.PATIENT and appt.patient.user_id == user.id:
        return
    if user.role == Role.DOCTOR and appt.doctor.user_id == user.id:
        return
    raise ForbiddenError("You do not have access to this appointment")


def get_appointment_for_user(db: Session, user: User, appointment_id: int) -> Appointment:
    appt = get_appointment(db, appointment_id)
    ensure_can_view(user, appt)
    return appt


def _ensure_can_change(user: User, appt: Appointment) -> None:
    """Patients can change only their own appointments; admins can change any."""
    if user.role == Role.ADMIN:
        return
    if user.role == Role.PATIENT and appt.patient.user_id == user.id:
        return
    raise ForbiddenError("You can manage only your own appointments")


def add_history(
    db: Session,
    appt: Appointment,
    old_status: AppointmentStatus | None,
    new_status: AppointmentStatus,
    user_id: int | None,
    note: str | None = None,
) -> None:
    db.add(
        AppointmentHistory(
            appointment_id=appt.id,
            old_status=old_status,
            new_status=new_status,
            changed_by_user_id=user_id,
            note=note,
        )
    )


def change_status(
    db: Session,
    appt: Appointment,
    new_status: AppointmentStatus,
    user_id: int | None = None,
    note: str | None = None,
) -> None:
    """Move an appointment to a new status and record it in the history table."""
    old_status = appt.status
    if new_status not in ALLOWED_TRANSITIONS[old_status]:
        raise BadRequestError(
            f"Invalid status change: {old_status.value} cannot become {new_status.value}"
        )
    appt.status = new_status
    # A cancelled appointment releases its slot (NULL is ignored by the unique constraints).
    appt.slot_active = None if new_status == S.CANCELLED else 1
    add_history(db, appt, old_status, new_status, user_id, note)


def recompute_tokens(db: Session, doctor_id: int, day: date) -> None:
    """Give every non-cancelled appointment of the day token 1, 2, 3... in slot-time order."""
    db.flush()
    appointments = db.scalars(
        select(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == day,
            Appointment.status != S.CANCELLED,
        )
        .order_by(Appointment.appointment_time, Appointment.id)
    ).all()
    for token, appt in enumerate(appointments, start=1):
        if appt.token_number != token:
            appt.token_number = token


def refresh_queue(doctor_id: int, day: date) -> None:
    """Push a live queue update (only today's queue is live)."""
    if day == clock.today():
        events.queue_changed(doctor_id)


# ---------------------------------------------------------------------------
# Validation shared by booking and rescheduling
# ---------------------------------------------------------------------------
def _validate_booking_window(day: date, at: time) -> None:
    today = clock.today()
    if day < today:
        raise BadRequestError("Appointments cannot be booked in the past")
    if day > today + timedelta(days=settings.MAX_BOOKING_DAYS_AHEAD):
        raise BadRequestError(
            f"Appointments can be booked only up to {settings.MAX_BOOKING_DAYS_AHEAD} days ahead"
        )
    if clock.slot_datetime(day, at) <= clock.now():
        raise BadRequestError("This time has already passed. Please choose a future slot")


def _validate_slot(
    db: Session, doctor: Doctor, day: date, at: time, exclude_appointment_id: int | None = None
) -> None:
    if at not in schedule_service.generate_day_slots(db, doctor, day):
        raise BadRequestError(
            "The doctor is not available at this time (outside working hours, during a break, "
            "on leave, or not a valid slot time)"
        )
    if at in schedule_service.booked_times(db, doctor.id, day, exclude_appointment_id):
        raise ConflictError("This slot is already booked. Please choose another slot")


def _check_patient_conflicts(
    db: Session,
    patient_id: int,
    doctor_id: int,
    day: date,
    at: time,
    exclude_appointment_id: int | None = None,
) -> None:
    base = select(Appointment.id).where(
        Appointment.patient_id == patient_id,
        Appointment.appointment_date == day,
        Appointment.status != S.CANCELLED,
    )
    if exclude_appointment_id is not None:
        base = base.where(Appointment.id != exclude_appointment_id)

    if db.scalar(base.where(Appointment.doctor_id == doctor_id).limit(1)) is not None:
        raise ConflictError("You already have an appointment with this doctor on this day")
    if db.scalar(base.where(Appointment.appointment_time == at).limit(1)) is not None:
        raise ConflictError("You already have another appointment at this date and time")


def _lock_doctor(db: Session, doctor_id: int, *, only_active: bool) -> Doctor:
    """Load the doctor row with a row lock so concurrent bookings are serialised."""
    stmt = select(Doctor).where(Doctor.id == doctor_id).with_for_update()
    doctor = db.scalar(stmt)
    if doctor is None or (only_active and not doctor.is_active):
        raise NotFoundError("Doctor not found")
    return doctor


def _next_appointment_number(db: Session, day: date) -> str:
    prefix = f"APT-{day.strftime('%Y%m%d')}-"
    last = db.scalar(
        select(Appointment.appointment_number)
        .where(Appointment.appointment_number.like(f"{prefix}%"))
        .order_by(func.length(Appointment.appointment_number).desc(), Appointment.appointment_number.desc())
        .limit(1)
    )
    sequence = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{sequence:04d}"


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
def book_appointment(
    db: Session, user: User, data: AppointmentCreate, background_tasks: BackgroundTasks | None = None
) -> Appointment:
    patient = db.scalar(select(Patient).where(Patient.user_id == user.id))
    if patient is None:
        raise NotFoundError("Patient profile not found for this account")

    doctor = _lock_doctor(db, data.doctor_id, only_active=True)
    day = data.appointment_date
    at = _normalise(data.appointment_time)

    _validate_booking_window(day, at)
    _validate_slot(db, doctor, day, at)
    _check_patient_conflicts(db, patient.id, doctor.id, day, at)

    appt = None
    for _attempt in range(5):
        number = _next_appointment_number(db, day)
        try:
            with db.begin_nested():  # SAVEPOINT: a failed insert keeps the doctor lock
                appt = Appointment(
                    appointment_number=number,
                    patient_id=patient.id,
                    doctor_id=doctor.id,
                    appointment_date=day,
                    appointment_time=at,
                    token_number=0,
                    reason=data.reason.strip(),
                    status=S.BOOKED,
                    consultation_fee=doctor.consultation_fee,  # copied: later fee changes do not affect it
                    slot_active=1,
                )
                db.add(appt)
                db.flush()
            break
        except IntegrityError as exc:
            appt = None
            if "appointment_number" in str(exc.orig).lower():
                continue  # another booking took the same number; try the next one
            raise ConflictError("This slot was just booked. Please choose another slot") from exc
    if appt is None:
        raise ConflictError("Could not create the appointment right now. Please try again")

    add_history(db, appt, None, S.BOOKED, user.id, "Appointment booked")
    recompute_tokens(db, doctor.id, day)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("This slot was just booked. Please choose another slot") from exc

    notification_service.appointment_booked(background_tasks, appt)
    refresh_queue(doctor.id, day)
    return appt


# ---------------------------------------------------------------------------
# Rescheduling / cancellation
# ---------------------------------------------------------------------------
def _ensure_two_hours_before(appt: Appointment, action: str) -> None:
    slot = clock.slot_datetime(appt.appointment_date, appt.appointment_time)
    if slot - clock.now() < timedelta(hours=settings.MIN_HOURS_BEFORE_CHANGE):
        raise BadRequestError(
            f"An appointment can be {action} only at least {settings.MIN_HOURS_BEFORE_CHANGE} hours before the slot"
        )


def reschedule_appointment(
    db: Session,
    user: User,
    appointment_id: int,
    data: RescheduleRequest,
    background_tasks: BackgroundTasks | None = None,
) -> Appointment:
    appt = get_appointment(db, appointment_id, lock=True)
    _ensure_can_change(user, appt)

    if appt.status != S.BOOKED:
        raise BadRequestError("Only booked appointments can be rescheduled")
    _ensure_two_hours_before(appt, "rescheduled")
    if appt.reschedule_count >= settings.MAX_RESCHEDULES:
        raise BadRequestError(f"An appointment can be rescheduled at most {settings.MAX_RESCHEDULES} times")

    doctor = _lock_doctor(db, appt.doctor_id, only_active=True)
    new_day = data.new_date
    new_time = _normalise(data.new_time)
    old_day, old_time = appt.appointment_date, appt.appointment_time

    if (new_day, new_time) == (old_day, old_time):
        raise BadRequestError("The new slot is the same as the current slot")

    _validate_booking_window(new_day, new_time)
    _validate_slot(db, doctor, new_day, new_time, exclude_appointment_id=appt.id)
    _check_patient_conflicts(db, appt.patient_id, doctor.id, new_day, new_time, exclude_appointment_id=appt.id)

    # Updating the date/time releases the old slot and takes the new one.
    appt.appointment_date = new_day
    appt.appointment_time = new_time
    appt.reschedule_count += 1
    appt.reminder_sent = False
    add_history(
        db,
        appt,
        S.BOOKED,
        S.BOOKED,
        user.id,
        f"Rescheduled from {old_day.isoformat()} {old_time.strftime('%H:%M')} "
        f"to {new_day.isoformat()} {new_time.strftime('%H:%M')}",
    )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("The new slot was just booked. Please choose another slot") from exc

    recompute_tokens(db, doctor.id, old_day)
    if new_day != old_day:
        recompute_tokens(db, doctor.id, new_day)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("The new slot was just booked. Please choose another slot") from exc

    notification_service.appointment_rescheduled(
        background_tasks, appt, old_day.strftime("%d %b %Y"), old_time.strftime("%H:%M")
    )
    refresh_queue(doctor.id, old_day)
    refresh_queue(doctor.id, new_day)
    return appt


def cancel_appointment_core(
    db: Session, appt: Appointment, user_id: int | None, reason: str | None
) -> None:
    """Cancel without commit (also used when a doctor's leave cancels appointments)."""
    change_status(db, appt, S.CANCELLED, user_id, note=reason or "Cancelled")
    appt.cancellation_reason = reason
    recompute_tokens(db, appt.doctor_id, appt.appointment_date)


def cancel_appointment(
    db: Session,
    user: User,
    appointment_id: int,
    reason: str | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> Appointment:
    appt = get_appointment(db, appointment_id, lock=True)
    _ensure_can_change(user, appt)

    if appt.status != S.BOOKED:
        raise BadRequestError("Only booked appointments can be cancelled")
    _ensure_two_hours_before(appt, "cancelled")

    cancel_appointment_core(db, appt, user.id, reason)
    db.commit()

    notification_service.appointment_cancelled(background_tasks, appt, reason)
    refresh_queue(appt.doctor_id, appt.appointment_date)
    return appt


# ---------------------------------------------------------------------------
# Check-in and no-show
# ---------------------------------------------------------------------------
def check_in(db: Session, user: User, appointment_id: int) -> Appointment:
    appt = get_appointment(db, appointment_id, lock=True)
    _ensure_can_change(user, appt)

    if appt.status != S.BOOKED:
        raise BadRequestError("Only booked appointments can be checked in")

    now = clock.now()
    if appt.appointment_date != now.date():
        raise BadRequestError("Check-in is possible only on the day of the appointment")
    opens_at = clock.slot_datetime(appt.appointment_date, appt.appointment_time) - timedelta(
        minutes=settings.CHECK_IN_OPENS_MINUTES_BEFORE
    )
    if now < opens_at:
        raise BadRequestError(
            f"Check-in opens {settings.CHECK_IN_OPENS_MINUTES_BEFORE} minutes before the appointment time"
        )

    change_status(db, appt, S.CHECKED_IN, user.id, note="Checked in")
    db.commit()

    events.notify_user(
        appt.patient.user_id,
        "checked_in",
        f"You are checked in (token {appt.token_number}). Please wait to be called.",
        {"appointment_id": appt.id, "token_number": appt.token_number},
    )
    events.queue_changed(appt.doctor_id)
    return appt


def mark_no_shows(db: Session) -> int:
    """Mark BOOKED appointments as NO_SHOW once the slot plus the grace period has passed.

    Called by the scheduler every 15 minutes. Returns how many were changed.
    """
    now = clock.now()
    grace = timedelta(minutes=settings.NO_SHOW_GRACE_MINUTES)
    candidates = db.scalars(
        select(Appointment).where(
            Appointment.status == S.BOOKED, Appointment.appointment_date <= now.date()
        )
    ).all()

    changed: list[Appointment] = []
    for appt in candidates:
        if clock.slot_datetime(appt.appointment_date, appt.appointment_time) + grace <= now:
            change_status(db, appt, S.NO_SHOW, None, note="Automatically marked as no-show")
            changed.append(appt)
    if not changed:
        return 0
    db.commit()

    for doctor_id in {a.doctor_id for a in changed}:
        events.queue_changed(doctor_id)
    logger.info("No-show job marked %d appointment(s)", len(changed))
    return len(changed)


# ---------------------------------------------------------------------------
# Listing and history
# ---------------------------------------------------------------------------
def list_appointments(
    db: Session,
    user: User,
    pagination: Pagination,
    *,
    status: AppointmentStatus | None = None,
    doctor_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    appointment_number: str | None = None,
):
    if date_from and date_to and date_from > date_to:
        raise BadRequestError("date_from must not be later than date_to")

    stmt = select(Appointment)
    if user.role == Role.PATIENT:
        stmt = stmt.join(Patient, Patient.id == Appointment.patient_id).where(Patient.user_id == user.id)
    elif user.role == Role.DOCTOR:
        stmt = stmt.join(Doctor, Doctor.id == Appointment.doctor_id).where(Doctor.user_id == user.id)

    if status is not None:
        stmt = stmt.where(Appointment.status == status)
    if doctor_id is not None:
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    if date_from is not None:
        stmt = stmt.where(Appointment.appointment_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Appointment.appointment_date <= date_to)
    if appointment_number:
        stmt = stmt.where(Appointment.appointment_number.ilike(f"%{appointment_number.strip()}%"))

    stmt = stmt.order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc(), Appointment.id.desc())
    return paginate(db, stmt, pagination)


def patient_history(db: Session, user: User, pagination: Pagination):
    """Past and current appointments of the logged-in patient with diagnosis and files."""
    patient = db.scalar(select(Patient).where(Patient.user_id == user.id))
    if patient is None:
        raise NotFoundError("Patient profile not found for this account")

    stmt = (
        select(Appointment)
        .where(Appointment.patient_id == patient.id)
        .order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc(), Appointment.id.desc())
    )
    appointments, total = paginate(db, stmt, pagination)

    items = [
        PatientHistoryItem(
            appointment_id=a.id,
            appointment_number=a.appointment_number,
            appointment_date=a.appointment_date,
            appointment_time=a.appointment_time,
            status=a.status,
            doctor_id=a.doctor_id,
            doctor_name=a.doctor_name,
            reason=a.reason,
            consultation=HistoryConsultationOut.model_validate(a.consultation) if a.consultation else None,
            files=[FileOut.model_validate(f) for f in a.files],
        )
        for a in appointments
    ]
    return items, total
