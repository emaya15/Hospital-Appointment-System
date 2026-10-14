"""Doctor weekly schedules, leave lookups and appointment-slot generation."""

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.enums import OPEN_STATUSES, AppointmentStatus
from app.models.schedule import DoctorLeave, DoctorSchedule
from app.models.user import User
from app.schemas.common import Pagination
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate
from app.services import doctor_service
from app.utils import clock
from app.utils.db import commit_or_conflict
from app.utils.exceptions import BadRequestError, ConflictError, NotFoundError
from app.utils.pagination import paginate

_DUMMY_DAY = date(2000, 1, 1)


def _plus(at: time, minutes: int) -> time | None:
    """Add minutes to a time of day. Returns None if the result passes midnight."""
    moment = datetime.combine(_DUMMY_DAY, at) + timedelta(minutes=minutes)
    if moment.date() != _DUMMY_DAY:
        return None
    return moment.time()


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
def _validate_times(
    start: time, end: time, break_start: time | None, break_end: time | None, slot_minutes: int
) -> None:
    if start >= end:
        raise BadRequestError("start_time must be earlier than end_time")
    if (break_start is None) != (break_end is None):
        raise BadRequestError("break_start and break_end must be given together")
    if break_start is not None and break_end is not None:
        if break_start >= break_end:
            raise BadRequestError("break_start must be earlier than break_end")
        if break_start < start or break_end > end:
            raise BadRequestError("The break must be inside the working hours")
    first_slot_end = _plus(start, slot_minutes)
    if first_slot_end is None or first_slot_end > end:
        raise BadRequestError("Working hours are shorter than one appointment slot")


def _check_overlap(
    db: Session, doctor_id: int, day: int, start: time, end: time, exclude_id: int | None = None
) -> None:
    stmt = select(DoctorSchedule).where(
        DoctorSchedule.doctor_id == doctor_id, DoctorSchedule.day_of_week == day
    )
    if exclude_id is not None:
        stmt = stmt.where(DoctorSchedule.id != exclude_id)
    for other in db.scalars(stmt).all():
        if start < other.end_time and end > other.start_time:
            raise ConflictError("This schedule overlaps with an existing schedule for the same day")


def _future_open_appointments_on_weekday(db: Session, doctor_id: int, weekday: int) -> bool:
    stmt = select(Appointment.appointment_date).where(
        Appointment.doctor_id == doctor_id,
        Appointment.status.in_(OPEN_STATUSES),
        Appointment.appointment_date >= clock.today(),
    )
    return any(d.weekday() == weekday for d in db.scalars(stmt).all())


def create_schedule(db: Session, user: User, doctor_id: int, data: ScheduleCreate) -> DoctorSchedule:
    doctor = doctor_service.get_doctor_or_404(db, doctor_id)
    doctor_service.ensure_can_manage(user, doctor)

    start = data.start_time.replace(second=0, microsecond=0)
    end = data.end_time.replace(second=0, microsecond=0)
    break_start = data.break_start.replace(second=0, microsecond=0) if data.break_start else None
    break_end = data.break_end.replace(second=0, microsecond=0) if data.break_end else None

    _validate_times(start, end, break_start, break_end, doctor.slot_duration_minutes)
    _check_overlap(db, doctor.id, data.day_of_week, start, end)

    schedule = DoctorSchedule(
        doctor_id=doctor.id,
        day_of_week=data.day_of_week,
        start_time=start,
        end_time=end,
        break_start=break_start,
        break_end=break_end,
    )
    db.add(schedule)
    db.commit()
    return schedule


def list_schedules(db: Session, doctor_id: int, pagination: Pagination):
    doctor_service.get_doctor_or_404(db, doctor_id)
    stmt = (
        select(DoctorSchedule)
        .where(DoctorSchedule.doctor_id == doctor_id)
        .order_by(DoctorSchedule.day_of_week, DoctorSchedule.start_time)
    )
    return paginate(db, stmt, pagination)


def _get_schedule(db: Session, schedule_id: int) -> DoctorSchedule:
    schedule = db.get(DoctorSchedule, schedule_id)
    if schedule is None:
        raise NotFoundError("Schedule not found")
    return schedule


def update_schedule(db: Session, user: User, schedule_id: int, data: ScheduleUpdate) -> DoctorSchedule:
    schedule = _get_schedule(db, schedule_id)
    doctor = doctor_service.get_doctor_or_404(db, schedule.doctor_id)
    doctor_service.ensure_can_manage(user, doctor)

    changes = data.model_dump(exclude_unset=True)
    day = changes.get("day_of_week", schedule.day_of_week)
    start = changes.get("start_time", schedule.start_time)
    end = changes.get("end_time", schedule.end_time)
    break_start = changes["break_start"] if "break_start" in changes else schedule.break_start
    break_end = changes["break_end"] if "break_end" in changes else schedule.break_end
    if day is None or start is None or end is None:
        raise BadRequestError("day_of_week, start_time and end_time cannot be null")

    start = start.replace(second=0, microsecond=0)
    end = end.replace(second=0, microsecond=0)
    break_start = break_start.replace(second=0, microsecond=0) if break_start else None
    break_end = break_end.replace(second=0, microsecond=0) if break_end else None

    _validate_times(start, end, break_start, break_end, doctor.slot_duration_minutes)
    _check_overlap(db, doctor.id, day, start, end, exclude_id=schedule.id)

    # Changing hours of a weekday that already has upcoming bookings could orphan them.
    for weekday in {schedule.day_of_week, day}:
        if _future_open_appointments_on_weekday(db, doctor.id, weekday):
            raise BadRequestError(
                "This weekday has upcoming appointments. Reschedule or cancel them before changing the schedule."
            )

    schedule.day_of_week = day
    schedule.start_time = start
    schedule.end_time = end
    schedule.break_start = break_start
    schedule.break_end = break_end
    db.commit()
    return schedule


def delete_schedule(db: Session, user: User, schedule_id: int) -> None:
    schedule = _get_schedule(db, schedule_id)
    doctor = doctor_service.get_doctor_or_404(db, schedule.doctor_id)
    doctor_service.ensure_can_manage(user, doctor)
    if _future_open_appointments_on_weekday(db, doctor.id, schedule.day_of_week):
        raise BadRequestError(
            "This weekday has upcoming appointments. Reschedule or cancel them before deleting the schedule."
        )
    db.delete(schedule)
    db.commit()


# ---------------------------------------------------------------------------
# Leave helpers (creating leave lives in leave_service.py)
# ---------------------------------------------------------------------------
def is_on_leave(db: Session, doctor_id: int, day: date) -> bool:
    stmt = select(DoctorLeave.id).where(
        DoctorLeave.doctor_id == doctor_id,
        DoctorLeave.start_date <= day,
        DoctorLeave.end_date >= day,
    )
    return db.scalar(stmt.limit(1)) is not None


# ---------------------------------------------------------------------------
# Slot generation
# ---------------------------------------------------------------------------
def generate_day_slots(db: Session, doctor: Doctor, day: date) -> list[time]:
    """All bookable slot start times of a day (ignores existing bookings and the clock).

    Slots follow the doctor's slot duration and skip breaks and leave days.
    """
    if is_on_leave(db, doctor.id, day):
        return []

    schedules = db.scalars(
        select(DoctorSchedule).where(
            DoctorSchedule.doctor_id == doctor.id, DoctorSchedule.day_of_week == day.weekday()
        )
    ).all()

    duration = doctor.slot_duration_minutes
    slots: set[time] = set()
    for schedule in schedules:
        cursor = schedule.start_time
        while True:
            slot_end = _plus(cursor, duration)
            if slot_end is None or slot_end > schedule.end_time:
                break
            in_break = (
                schedule.break_start is not None
                and schedule.break_end is not None
                and cursor < schedule.break_end
                and slot_end > schedule.break_start
            )
            if not in_break:
                slots.add(cursor)
            cursor = slot_end
    return sorted(slots)


def booked_times(
    db: Session, doctor_id: int, day: date, exclude_appointment_id: int | None = None
) -> set[time]:
    stmt = select(Appointment.appointment_time).where(
        Appointment.doctor_id == doctor_id,
        Appointment.appointment_date == day,
        Appointment.status != AppointmentStatus.CANCELLED,
    )
    if exclude_appointment_id is not None:
        stmt = stmt.where(Appointment.id != exclude_appointment_id)
    return set(db.scalars(stmt).all())


def available_slots(db: Session, doctor: Doctor, day: date) -> list[time]:
    """Free slots: not booked, not in the past, not on a break or leave day."""
    now = clock.now()
    taken = booked_times(db, doctor.id, day)
    return [
        slot
        for slot in generate_day_slots(db, doctor, day)
        if slot not in taken and clock.slot_datetime(day, slot) > now
    ]
