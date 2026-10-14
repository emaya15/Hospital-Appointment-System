"""Builds e-mails and WebSocket notifications for appointment events.

Services call these helpers after committing. E-mails are queued as background tasks;
WebSocket messages are pushed to the patient (and the doctor) if they are connected.
All values are copied into plain strings first, so background tasks never touch the DB.
"""

from fastapi import BackgroundTasks

from app.config import settings
from app.models.appointment import Appointment
from app.models.consultation import Consultation
from app.services import email_service
from app.services.email_service import EmailMessage
from app.websockets import events


def _details(appt: Appointment) -> dict:
    return {
        "number": appt.appointment_number,
        "date": appt.appointment_date.strftime("%d %b %Y"),
        "time": appt.appointment_time.strftime("%H:%M"),
        "doctor": appt.doctor.user.full_name,
        "patient": appt.patient.user.full_name,
        "email": appt.patient.user.email,
        "token": appt.token_number,
        "hospital": settings.HOSPITAL_NAME,
    }


def _ws_data(appt: Appointment) -> dict:
    return {
        "appointment_id": appt.id,
        "appointment_number": appt.appointment_number,
        "doctor_id": appt.doctor_id,
        "date": appt.appointment_date.isoformat(),
        "time": appt.appointment_time.strftime("%H:%M"),
        "status": appt.status.value,
    }


def _notify_both(appt: Appointment, event: str, patient_message: str, doctor_message: str) -> None:
    data = _ws_data(appt)
    events.notify_user(appt.patient.user_id, event, patient_message, data)
    events.notify_user(appt.doctor.user_id, event, doctor_message, data)


# --------------------------------------------------------------------------- booking
def appointment_booked(background_tasks: BackgroundTasks | None, appt: Appointment) -> None:
    d = _details(appt)
    body = (
        f"Dear {d['patient']},\n\n"
        f"Your appointment is confirmed.\n\n"
        f"Appointment number: {d['number']}\n"
        f"Doctor: {d['doctor']}\n"
        f"Date: {d['date']}\n"
        f"Time: {d['time']}\n"
        f"Token number: {d['token']}\n\n"
        f"Please arrive 15 minutes early.\n\n{d['hospital']}"
    )
    email_service.dispatch(
        background_tasks, EmailMessage(d["email"], f"Appointment confirmed - {d['number']}", body)
    )
    _notify_both(
        appt,
        "appointment_booked",
        f"Your appointment {d['number']} is booked for {d['date']} at {d['time']}.",
        f"New appointment {d['number']} on {d['date']} at {d['time']}.",
    )


def appointment_rescheduled(
    background_tasks: BackgroundTasks | None, appt: Appointment, old_date: str, old_time: str
) -> None:
    d = _details(appt)
    body = (
        f"Dear {d['patient']},\n\n"
        f"Your appointment {d['number']} with {d['doctor']} was rescheduled.\n\n"
        f"Old slot: {old_date} {old_time}\n"
        f"New slot: {d['date']} {d['time']}\n"
        f"New token number: {d['token']}\n\n{d['hospital']}"
    )
    email_service.dispatch(
        background_tasks, EmailMessage(d["email"], f"Appointment rescheduled - {d['number']}", body)
    )
    _notify_both(
        appt,
        "appointment_rescheduled",
        f"Your appointment {d['number']} is now on {d['date']} at {d['time']}.",
        f"Appointment {d['number']} moved to {d['date']} at {d['time']}.",
    )


def appointment_cancelled(
    background_tasks: BackgroundTasks | None,
    appt: Appointment,
    reason: str | None = None,
    *,
    doctor_leave: bool = False,
) -> None:
    d = _details(appt)
    why = "The doctor is on leave on that day." if doctor_leave else (f"Reason: {reason}" if reason else "")
    body = (
        f"Dear {d['patient']},\n\n"
        f"Your appointment {d['number']} with {d['doctor']} on {d['date']} at {d['time']} "
        f"has been cancelled.\n{why}\n\n"
        f"You can book a new appointment at any time.\n\n{d['hospital']}"
    )
    subject = (
        f"Appointment cancelled (doctor on leave) - {d['number']}"
        if doctor_leave
        else f"Appointment cancelled - {d['number']}"
    )
    email_service.dispatch(background_tasks, EmailMessage(d["email"], subject, body))
    _notify_both(
        appt,
        "appointment_cancelled",
        f"Your appointment {d['number']} on {d['date']} at {d['time']} was cancelled.",
        f"Appointment {d['number']} on {d['date']} at {d['time']} was cancelled.",
    )


# --------------------------------------------------------------------------- consultation
def consultation_completed(
    background_tasks: BackgroundTasks | None, appt: Appointment, consultation: Consultation
) -> None:
    d = _details(appt)
    follow_up = (
        f"\nFollow-up date: {consultation.follow_up_date.strftime('%d %b %Y')}"
        if consultation.follow_up_date
        else ""
    )
    body = (
        f"Dear {d['patient']},\n\n"
        f"Your consultation with {d['doctor']} (appointment {d['number']}) is complete.\n"
        f"You can download your prescription from the patient portal.{follow_up}\n\n"
        f"Wishing you good health,\n{d['hospital']}"
    )
    email_service.dispatch(
        background_tasks, EmailMessage(d["email"], f"Consultation completed - {d['number']}", body)
    )
    events.notify_user(
        appt.patient.user_id,
        "consultation_completed",
        f"Your consultation for {d['number']} is complete.",
        _ws_data(appt),
    )


# --------------------------------------------------------------------------- reminders (jobs)
def build_appointment_reminder(appt: Appointment) -> EmailMessage:
    d = _details(appt)
    body = (
        f"Dear {d['patient']},\n\n"
        f"This is a reminder of your appointment.\n\n"
        f"Appointment number: {d['number']}\n"
        f"Doctor: {d['doctor']}\n"
        f"Date: {d['date']}\n"
        f"Time: {d['time']}\n\n"
        f"Please arrive 15 minutes early. If you cannot attend, cancel at least 2 hours before.\n\n"
        f"{d['hospital']}"
    )
    return EmailMessage(d["email"], f"Appointment reminder - {d['number']}", body)


def build_followup_reminder(appt: Appointment, consultation: Consultation) -> EmailMessage:
    d = _details(appt)
    when = consultation.follow_up_date.strftime("%d %b %Y") if consultation.follow_up_date else "tomorrow"
    body = (
        f"Dear {d['patient']},\n\n"
        f"Dr. {d['doctor']} advised a follow-up visit for you on {when}.\n"
        f"Please book an appointment if you have not done so already.\n\n{d['hospital']}"
    )
    return EmailMessage(d["email"], "Follow-up reminder", body)
