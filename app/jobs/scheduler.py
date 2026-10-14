"""APScheduler jobs.

* appointment reminders - every hour, for appointments in the next 24 hours
* no-show detection     - every 15 minutes
* follow-up reminders   - daily at 09:00, for follow-ups scheduled for tomorrow

Each job opens its own database session, never raises (errors are logged) and is safe
to run twice: reminders use flags (``reminder_sent`` / ``follow_up_reminder_sent``) that
are set only after the e-mail was sent successfully.
"""

import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models.appointment import Appointment
from app.models.consultation import Consultation
from app.models.enums import AppointmentStatus
from app.services import appointment_service, email_service, notification_service
from app.utils import clock

logger = logging.getLogger(__name__)


def send_appointment_reminders() -> int:
    """E-mail patients whose BOOKED appointment starts within the next 24 hours."""
    sent = 0
    try:
        with SessionLocal() as db:
            now = clock.now()
            candidates = db.scalars(
                select(Appointment).where(
                    Appointment.status == AppointmentStatus.BOOKED,
                    Appointment.reminder_sent.is_(False),
                    Appointment.appointment_date >= now.date(),
                    Appointment.appointment_date <= (now + timedelta(hours=24)).date(),
                )
            ).all()

            for appt in candidates:
                slot = clock.slot_datetime(appt.appointment_date, appt.appointment_time)
                if not (now <= slot <= now + timedelta(hours=24)):
                    continue
                if email_service.send_email(notification_service.build_appointment_reminder(appt)):
                    appt.reminder_sent = True  # only after a successful send, so failures are retried
                    db.commit()
                    sent += 1
    except Exception:  # noqa: BLE001 - a scheduled job must never crash the scheduler
        logger.exception("Appointment reminder job failed")
    logger.info("Reminder job finished: %d reminder(s) sent", sent)
    return sent


def detect_no_shows() -> int:
    """Mark BOOKED appointments as NO_SHOW once the slot + grace period has passed."""
    try:
        with SessionLocal() as db:
            return appointment_service.mark_no_shows(db)
    except Exception:  # noqa: BLE001
        logger.exception("No-show job failed")
        return 0


def send_followup_reminders() -> int:
    """E-mail patients whose follow-up date is tomorrow."""
    sent = 0
    try:
        with SessionLocal() as db:
            tomorrow = clock.today() + timedelta(days=1)
            consultations = db.scalars(
                select(Consultation).where(
                    Consultation.follow_up_date == tomorrow,
                    Consultation.follow_up_reminder_sent.is_(False),
                )
            ).all()
            for consultation in consultations:
                message = notification_service.build_followup_reminder(consultation.appointment, consultation)
                if email_service.send_email(message):
                    consultation.follow_up_reminder_sent = True
                    db.commit()
                    sent += 1
    except Exception:  # noqa: BLE001
        logger.exception("Follow-up reminder job failed")
    logger.info("Follow-up job finished: %d reminder(s) sent", sent)
    return sent


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=clock.TZ)
    common = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}
    scheduler.add_job(
        send_appointment_reminders, "interval", hours=1, id="appointment_reminders", **common
    )
    scheduler.add_job(detect_no_shows, "interval", minutes=15, id="no_show_detection", **common)
    scheduler.add_job(
        send_followup_reminders, "cron", hour=9, minute=0, id="followup_reminders", **common
    )
    return scheduler


def start_scheduler() -> BackgroundScheduler | None:
    if not settings.SCHEDULER_ENABLED:
        logger.info("Scheduler is disabled (SCHEDULER_ENABLED=false)")
        return None
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler started with %d job(s)", len(scheduler.get_jobs()))
    return scheduler
