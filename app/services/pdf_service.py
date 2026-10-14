"""Prescription PDF generation (ReportLab).

PDFs are written to PDF_DIR (excluded from Git). The file name comes only from the
appointment number (letters, digits and dashes), never from user input.
"""

import logging
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.config import settings
from app.models.appointment import Appointment
from app.models.consultation import Consultation
from app.models.user import User
from app.services import appointment_service
from app.utils.exceptions import NotFoundError

logger = logging.getLogger(__name__)

BLUE = colors.HexColor("#1f4e79")
LIGHT = colors.HexColor("#eaf1f8")


def _text(value) -> str:
    """Escape user text for ReportLab paragraphs and keep line breaks."""
    return escape(str(value)).replace("\n", "<br/>")


def pdf_path_for(appt: Appointment) -> Path:
    return settings.PDF_DIR / f"prescription_{appt.appointment_number}.pdf"


def generate_prescription_pdf(appt: Appointment, consultation: Consultation) -> Path:
    """Create (or overwrite) the prescription PDF of an appointment and return its path."""
    settings.PDF_DIR.mkdir(parents=True, exist_ok=True)
    path = pdf_path_for(appt)

    styles = getSampleStyleSheet()
    title = ParagraphStyle("Title2", parent=styles["Title"], textColor=BLUE, fontSize=20, spaceAfter=2)
    sub = ParagraphStyle("Sub", parent=styles["Normal"], alignment=1, textColor=colors.grey, fontSize=9)
    heading = ParagraphStyle("Head", parent=styles["Heading3"], textColor=BLUE, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("Body2", parent=styles["Normal"], fontSize=10, leading=14)

    doctor = appt.doctor
    patient = appt.patient
    story = [
        Paragraph(_text(settings.HOSPITAL_NAME), title),
        Paragraph("Medical Prescription", sub),
        Spacer(1, 8 * mm),
    ]

    info_rows = [
        ["Appointment No.", appt.appointment_number, "Date", appt.appointment_date.strftime("%d %b %Y")],
        ["Doctor", doctor.user.full_name, "Time", appt.appointment_time.strftime("%H:%M")],
        ["Specialization", doctor.specialization, "Qualification", doctor.qualification],
        ["Patient", patient.user.full_name, "Phone", patient.user.phone],
        [
            "Gender",
            patient.gender or "-",
            "Date of birth",
            patient.date_of_birth.strftime("%d %b %Y") if patient.date_of_birth else "-",
        ],
    ]
    cell = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=9, leading=11)
    info = Table(
        [[Paragraph(_text(c), cell) for c in row] for row in info_rows],
        colWidths=[32 * mm, 55 * mm, 28 * mm, 55 * mm],
    )
    info.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LIGHT),
                ("BACKGROUND", (2, 0), (2, -1), LIGHT),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story += [info, Spacer(1, 4 * mm)]

    story += [Paragraph("Symptoms", heading), Paragraph(_text(consultation.symptoms), body)]
    story += [Paragraph("Diagnosis", heading), Paragraph(_text(consultation.diagnosis), body)]

    story.append(Paragraph("Medicines", heading))
    if consultation.prescription:
        header = ["#", "Medicine", "Dosage", "Duration"]
        rows = [header] + [
            [str(i), item.medicine, item.dosage, item.duration]
            for i, item in enumerate(consultation.prescription, start=1)
        ]
        meds = Table(
            [[Paragraph(_text(c), cell) for c in row] for row in rows],
            colWidths=[10 * mm, 80 * mm, 50 * mm, 30 * mm],
            repeatRows=1,
        )
        meds.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(meds)
    else:
        story.append(Paragraph("No medicines prescribed.", body))

    if consultation.advice:
        story += [Paragraph("Advice", heading), Paragraph(_text(consultation.advice), body)]
    if consultation.follow_up_date:
        story += [
            Paragraph("Follow-up", heading),
            Paragraph(f"Please visit again on {consultation.follow_up_date.strftime('%d %b %Y')}.", body),
        ]

    story += [
        Spacer(1, 18 * mm),
        Paragraph(f"Dr. {_text(doctor.user.full_name)}", ParagraphStyle("Sig", parent=body, alignment=2)),
        Paragraph("This is a computer generated prescription.", sub),
    ]

    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Prescription {appt.appointment_number}",
        author=settings.HOSPITAL_NAME,
    )
    document.build(story)
    return path


def get_prescription_pdf(db: Session, user: User, appointment_id: int) -> Path:
    """Return the PDF path if the user may access this appointment (404 if no consultation)."""
    appt = appointment_service.get_appointment_for_user(db, user, appointment_id)
    consultation = appt.consultation
    if consultation is None:
        raise NotFoundError("No consultation has been recorded for this appointment yet")

    path = pdf_path_for(appt)
    if not path.exists():
        path = generate_prescription_pdf(appt, consultation)
    return path
