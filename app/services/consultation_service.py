"""Recording consultations. Saving one completes the appointment."""

import logging

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.models.consultation import Consultation, PrescriptionItem
from app.models.enums import AppointmentStatus
from app.models.user import User
from app.schemas.consultation import ConsultationCreate
from app.services import appointment_service, doctor_service, notification_service, pdf_service
from app.utils.db import commit_or_conflict
from app.utils.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.websockets import events

logger = logging.getLogger(__name__)


def create_consultation(
    db: Session,
    user: User,
    appointment_id: int,
    data: ConsultationCreate,
    background_tasks: BackgroundTasks | None = None,
) -> Consultation:
    appt = appointment_service.get_appointment(db, appointment_id, lock=True)

    doctor = doctor_service.get_doctor_for_user(db, user)
    if appt.doctor_id != doctor.id:
        raise ForbiddenError("Only the assigned doctor can record this consultation")
    if appt.status != AppointmentStatus.IN_CONSULTATION:
        raise BadRequestError("A consultation can be recorded only while the appointment is In Consultation")
    if appt.consultation is not None:
        raise ConflictError("A consultation has already been recorded for this appointment")
    if data.follow_up_date is not None and data.follow_up_date <= appt.appointment_date:
        raise BadRequestError("follow_up_date must be after the appointment date")

    consultation = Consultation(
        appointment_id=appt.id,
        symptoms=data.symptoms.strip(),
        diagnosis=data.diagnosis.strip(),
        advice=data.advice.strip() if data.advice else None,
        follow_up_date=data.follow_up_date,
        prescription=[
            PrescriptionItem(medicine=i.medicine.strip(), dosage=i.dosage.strip(), duration=i.duration.strip())
            for i in data.prescription
        ],
    )
    db.add(consultation)
    appointment_service.change_status(
        db, appt, AppointmentStatus.COMPLETED, user.id, note="Consultation saved"
    )
    commit_or_conflict(db, "A consultation has already been recorded for this appointment")

    # Everything below happens AFTER the commit, so a failure here cannot undo the visit.
    try:
        pdf_service.generate_prescription_pdf(appt, consultation)
    except Exception:  # noqa: BLE001 - the PDF is regenerated on download if this fails
        logger.exception("Could not pre-generate the prescription PDF for %s", appt.appointment_number)

    notification_service.consultation_completed(background_tasks, appt, consultation)
    events.queue_changed(appt.doctor_id)
    return consultation


def get_consultation(db: Session, user: User, appointment_id: int) -> Consultation:
    appt = appointment_service.get_appointment_for_user(db, user, appointment_id)
    if appt.consultation is None:
        raise NotFoundError("No consultation has been recorded for this appointment yet")
    return appt.consultation
