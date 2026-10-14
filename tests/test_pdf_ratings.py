from app.config import settings
from tests.conftest import auth, book, future_weekday, to_in_consultation

CONSULTATION = {
    "symptoms": "Fever",
    "diagnosis": "Viral infection <b>test</b> & rest",
    "prescription": [
        {"medicine": "Paracetamol", "dosage": "500mg twice daily", "duration": "5 days"},
        {"medicine": "ORS", "dosage": "1 sachet", "duration": "3 days"},
    ],
    "advice": "Drink plenty of fluids",
}


def _completed(client, setup_doctor, register_patient, monkeypatch):
    doctor_id = setup_doctor()
    patient = register_patient()
    appointment, _day, doctor = to_in_consultation(client, monkeypatch, doctor_id, patient)
    assert client.post(f"/appointments/{appointment['id']}/consultation", json=CONSULTATION, headers=doctor).status_code == 201
    return doctor_id, appointment, patient, doctor


def test_prescription_pdf_is_generated_and_downloadable(client, setup_doctor, register_patient, monkeypatch, admin_headers):
    _doctor_id, appointment, patient, doctor = _completed(client, setup_doctor, register_patient, monkeypatch)
    url = f"/appointments/{appointment['id']}/prescription-pdf"

    for headers in (patient, doctor, admin_headers):
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")
    stored = list(settings.PDF_DIR.glob("*.pdf"))
    assert len(stored) == 1 and appointment["appointment_number"] in stored[0].name


def test_prescription_pdf_is_regenerated_if_missing(client, setup_doctor, register_patient, monkeypatch):
    _doctor_id, appointment, patient, _doctor = _completed(client, setup_doctor, register_patient, monkeypatch)
    for pdf in settings.PDF_DIR.glob("*.pdf"):
        pdf.unlink()
    assert client.get(f"/appointments/{appointment['id']}/prescription-pdf", headers=patient).status_code == 200


def test_prescription_pdf_authorization(client, setup_doctor, register_patient, monkeypatch):
    _doctor_id, appointment, _patient, _doctor = _completed(client, setup_doctor, register_patient, monkeypatch)
    url = f"/appointments/{appointment['id']}/prescription-pdf"
    stranger = register_patient("s@test.com", phone="9000000008")
    assert client.get(url, headers=stranger).status_code == 403
    assert client.get(url).status_code == 401
    assert client.get("/appointments/9999/prescription-pdf", headers=stranger).status_code == 404


def test_pdf_not_available_before_consultation(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    patient = register_patient()
    appointment = book(client, patient, doctor_id, future_weekday(3), "09:00").json()
    assert client.get(f"/appointments/{appointment['id']}/prescription-pdf", headers=patient).status_code == 404


def test_pdf_service_generates_valid_file_with_special_characters(client, setup_doctor, register_patient, monkeypatch, db):
    from app.models import Appointment
    from app.services import pdf_service

    _doctor_id, appointment, _patient, _doctor = _completed(client, setup_doctor, register_patient, monkeypatch)
    appt = db.get(Appointment, appointment["id"])
    path = pdf_service.generate_prescription_pdf(appt, appt.consultation)
    assert path.exists() and path.stat().st_size > 800
    assert path.read_bytes()[:5] == b"%PDF-"


def test_rating_rules(client, setup_doctor, register_patient, monkeypatch):
    doctor_id = setup_doctor()
    patient = register_patient()
    day = future_weekday(4)
    pending = book(client, patient, doctor_id, day, "09:00").json()
    rate = {"rating": 5, "review": "Great doctor"}
    # cannot rate before the appointment is completed
    assert client.post(f"/appointments/{pending['id']}/rating", json=rate, headers=patient).status_code == 400

    appointment, _day, doctor = to_in_consultation(client, monkeypatch, doctor_id, register_patient("p2@test.com", phone="9000000002"), at="10:00", days=5)
    client.post(f"/appointments/{appointment['id']}/consultation", json=CONSULTATION, headers=doctor)
    owner = auth(client, "p2@test.com")
    url = f"/appointments/{appointment['id']}/rating"

    assert client.post(url, json={"rating": 6}, headers=owner).status_code == 422
    assert client.post(url, json={"rating": 0}, headers=owner).status_code == 422
    assert client.post(url, json=rate, headers=patient).status_code == 403          # someone else's appointment
    assert client.post(url, json=rate, headers=doctor).status_code == 403            # doctors cannot rate
    created = client.post(url, json=rate, headers=owner)
    assert created.status_code == 201 and created.json()["doctor_id"] == doctor_id
    assert client.post(url, json={"rating": 1}, headers=owner).status_code == 409    # one rating per appointment

    summary = client.get(f"/doctors/{doctor_id}/ratings", headers=patient).json()
    assert summary["total_ratings"] == 1 and summary["average_rating"] == 5.0
    assert summary["ratings"][0]["review"] == "Great doctor"
    assert client.get("/doctors/9999/ratings", headers=patient).status_code == 404


def test_average_rating_across_appointments(client, setup_doctor, register_patient, monkeypatch):
    doctor_id = setup_doctor()
    scores = []
    for index, (score, days, at) in enumerate([(5, 4, "09:00"), (2, 5, "09:00")]):
        email = f"r{index}@test.com"
        patient = register_patient(email, phone=f"900000001{index}")
        appointment, _day, doctor = to_in_consultation(client, monkeypatch, doctor_id, patient, at=at, days=days)
        client.post(f"/appointments/{appointment['id']}/consultation", json=CONSULTATION, headers=doctor)
        assert client.post(f"/appointments/{appointment['id']}/rating", json={"rating": score}, headers=auth(client, email)).status_code == 201
    summary = client.get(f"/doctors/{doctor_id}/ratings", headers=auth(client, "r0@test.com")).json()
    assert summary["total_ratings"] == 2 and summary["average_rating"] == 3.5
