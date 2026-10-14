"""Live queue state and the "call next patient" action.

Queue rules
-----------
* Only patients who are CHECKED_IN wait in the queue; they are served in token order.
* A patient is called with PUT /doctors/me/call-next, which moves them to IN_CONSULTATION.
* The next patient can be called only after the current consultation has been saved
  (saving it moves the appointment to COMPLETED).
* Estimated wait = people ahead of you (including the one in consultation) x slot length.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.enums import AppointmentStatus
from app.models.user import User
from app.services import appointment_service, doctor_service
from app.utils import clock
from app.utils.exceptions import BadRequestError, NotFoundError
from app.websockets import events

S = AppointmentStatus


def build_snapshot(db: Session, doctor_id: int, day: date | None = None) -> dict | None:
    """Current queue of one doctor for one day (default: today). None if no such doctor."""
    doctor = db.get(Doctor, doctor_id)
    if doctor is None:
        return None
    day = day or clock.today()

    appointments = db.scalars(
        select(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == day,
            Appointment.status.in_([S.CHECKED_IN, S.IN_CONSULTATION]),
        )
        .order_by(Appointment.token_number, Appointment.id)
    ).all()

    current = next((a for a in appointments if a.status == S.IN_CONSULTATION), None)
    waiting = [a for a in appointments if a.status == S.CHECKED_IN]
    in_consultation = 1 if current else 0

    entries = []
    for position, appt in enumerate(waiting, start=1):
        entries.append(
            {
                "appointment_id": appt.id,
                "appointment_number": appt.appointment_number,
                "patient_user_id": appt.patient.user_id,
                "token_number": appt.token_number,
                "position": position,
                "estimated_wait_minutes": (position - 1 + in_consultation) * doctor.slot_duration_minutes,
            }
        )

    return {
        "doctor_id": doctor_id,
        "date": day.isoformat(),
        "current_token": current.token_number if current else None,
        "current_patient_user_id": current.patient.user_id if current else None,
        "waiting_count": len(waiting),
        "entries": entries,
    }


def call_next(db: Session, user: User) -> Appointment:
    """The logged-in doctor calls the next checked-in patient."""
    doctor_ref = doctor_service.get_doctor_for_user(db, user)
    # Lock the doctor row so two simultaneous calls cannot both succeed.
    doctor = db.scalar(select(Doctor).where(Doctor.id == doctor_ref.id).with_for_update())
    today = clock.today()

    in_progress = db.scalar(
        select(Appointment.id)
        .where(
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date == today,
            Appointment.status == S.IN_CONSULTATION,
        )
        .limit(1)
    )
    if in_progress is not None:
        raise BadRequestError("Save the current consultation before calling the next patient")

    nxt = db.scalar(
        select(Appointment)
        .where(
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date == today,
            Appointment.status == S.CHECKED_IN,
        )
        .order_by(Appointment.token_number, Appointment.id)
        .limit(1)
    )
    if nxt is None:
        raise NotFoundError("No checked-in patients are waiting")

    appointment_service.change_status(db, nxt, S.IN_CONSULTATION, user.id, note="Called by doctor")
    db.commit()

    events.notify_user(
        nxt.patient.user_id,
        "your_turn",
        f"Token {nxt.token_number}: please proceed to the consultation room",
        {"appointment_id": nxt.id, "token_number": nxt.token_number},
    )
    events.queue_changed(doctor.id)
    return nxt
