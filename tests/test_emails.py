import logging
import smtplib

from app.config import settings
from app.services import email_service
from app.services.email_service import EmailMessage
from tests.conftest import book, future_weekday


def _message():
    return EmailMessage("patient@example.com", "Hello", "Body with private details")


def test_mock_mode_records_without_network(monkeypatch):
    monkeypatch.setattr(settings, "MAIL_MODE", "mock")
    assert email_service.send_email(_message()) is True
    assert email_service.sent_mock_emails[-1].subject == "Hello"


def test_missing_smtp_credentials_logs_and_returns_false(monkeypatch, caplog):
    monkeypatch.setattr(settings, "MAIL_MODE", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    with caplog.at_level(logging.WARNING):
        assert email_service.send_email(_message()) is False
    assert "SMTP_HOST" in caplog.text


def test_smtp_failure_is_logged_without_secrets_and_never_raises(monkeypatch, caplog):
    monkeypatch.setattr(settings, "MAIL_MODE", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.invalid")
    monkeypatch.setattr(settings, "SMTP_FROM", "hospital@example.com")
    monkeypatch.setattr(settings, "SMTP_USERNAME", "hospital@example.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "super-secret-password")

    def broken(*_args, **_kwargs):
        raise smtplib.SMTPConnectError(421, "service unavailable")

    monkeypatch.setattr(smtplib, "SMTP", broken)
    with caplog.at_level(logging.INFO):
        assert email_service.send_email(_message()) is False
    assert "super-secret-password" not in caplog.text
    assert "Body with private details" not in caplog.text
    assert "patient@example.com" not in caplog.text   # recipient is masked in logs


def test_booking_still_succeeds_when_email_fails(client, setup_doctor, register_patient, monkeypatch):
    doctor_id = setup_doctor()
    patient = register_patient()
    monkeypatch.setattr(settings, "MAIL_MODE", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.invalid")
    monkeypatch.setattr(settings, "SMTP_FROM", "hospital@example.com")
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(OSError("network down")))

    response = book(client, patient, doctor_id, future_weekday(3))
    assert response.status_code == 201            # the e-mail failure did not undo the booking
    assert client.get("/appointments", headers=patient).json()["total"] == 1


def test_reminder_job_sends_once_and_sets_flag(client, setup_doctor, register_patient, monkeypatch, db):
    from datetime import timedelta
    from app.jobs.scheduler import send_appointment_reminders
    from app.models import Appointment
    from tests.conftest import at_slot, freeze_now

    doctor_id = setup_doctor()
    patient = register_patient()
    day = future_weekday(3)
    appointment = book(client, patient, doctor_id, day, "10:00").json()

    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(hours=-30)))
    assert send_appointment_reminders() == 0                  # more than 24 hours away
    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(hours=-20)))
    email_service.sent_mock_emails.clear()
    assert send_appointment_reminders() == 1
    assert send_appointment_reminders() == 0                  # reminder_sent flag prevents duplicates
    assert len([m for m in email_service.sent_mock_emails if "reminder" in m.subject.lower()]) == 1
    db.expire_all()
    assert db.get(Appointment, appointment["id"]).reminder_sent is True


def test_failed_reminder_is_retried(client, setup_doctor, register_patient, monkeypatch):
    from datetime import timedelta
    from app.jobs.scheduler import send_appointment_reminders
    from tests.conftest import at_slot, freeze_now

    doctor_id = setup_doctor()
    day = future_weekday(3)
    book(client, register_patient(), doctor_id, day, "10:00")
    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(hours=-5)))

    monkeypatch.setattr(email_service, "send_email", lambda _m: False)
    assert send_appointment_reminders() == 0
    monkeypatch.undo()
    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(hours=-5)))
    assert send_appointment_reminders() == 1


def test_followup_job_targets_tomorrow(client, setup_doctor, register_patient, monkeypatch):
    from datetime import timedelta
    from app.jobs.scheduler import send_followup_reminders
    from tests.conftest import freeze_now, to_in_consultation

    doctor_id = setup_doctor()
    patient = register_patient()
    appointment, day, doctor = to_in_consultation(client, monkeypatch, doctor_id, patient)
    follow_up = day + timedelta(days=7)
    saved = client.post(
        f"/appointments/{appointment['id']}/consultation",
        json={"symptoms": "cough", "diagnosis": "cold", "follow_up_date": follow_up.isoformat()}, headers=doctor,
    )
    assert saved.status_code == 201

    from tests.conftest import at_slot
    freeze_now(monkeypatch, at_slot(follow_up - timedelta(days=2), "09:00"))
    assert send_followup_reminders() == 0
    freeze_now(monkeypatch, at_slot(follow_up - timedelta(days=1), "09:00"))
    assert send_followup_reminders() == 1
    assert send_followup_reminders() == 0


def test_scheduler_registers_the_three_jobs():
    from app.jobs.scheduler import create_scheduler

    scheduler = create_scheduler()
    scheduler.start(paused=True)
    try:
        ids = {job.id for job in scheduler.get_jobs()}
    finally:
        scheduler.shutdown(wait=False)
    assert ids == {"appointment_reminders", "no_show_detection", "followup_reminders"}
