from datetime import timedelta

from tests.conftest import at_slot, auth, book, freeze_now, future_weekday, to_in_consultation

CONSULTATION = {
    "symptoms": "Chest pain, dizziness",
    "diagnosis": "Mild angina",
    "prescription": [{"medicine": "Aspirin", "dosage": "75mg once daily", "duration": "30 days"}],
    "advice": "Avoid heavy exercise",
}


def test_call_next_follows_token_order_and_waits_for_consultation(client, setup_doctor, register_patient, monkeypatch, admin_headers):
    doctor_id = setup_doctor()
    day = future_weekday(4)
    first = register_patient("p1@test.com", phone="9000000002")
    second = register_patient("p2@test.com", phone="9000000003")
    a = book(client, first, doctor_id, day, "10:00").json()
    b = book(client, second, doctor_id, day, "09:30").json()    # earlier slot -> token 1

    freeze_now(monkeypatch, at_slot(day, "09:30", timedelta(minutes=5)))   # 09:35: check-in is open for 09:30 and 10:00
    for appointment in (a, b):
        assert client.put(f"/appointments/{appointment['id']}/check-in", headers=admin_headers).status_code == 200

    doctor = auth(client, "doc@test.com")
    called = client.put("/doctors/me/call-next", headers=doctor).json()
    assert called["id"] == b["id"] and called["status"] == "IN_CONSULTATION"
    # the next patient cannot be called before the current consultation is saved
    assert client.put("/doctors/me/call-next", headers=doctor).status_code == 400

    saved = client.post(f"/appointments/{b['id']}/consultation", json=CONSULTATION, headers=doctor)
    assert saved.status_code == 201, saved.text
    nxt = client.put("/doctors/me/call-next", headers=doctor).json()
    assert nxt["id"] == a["id"]
    client.post(f"/appointments/{a['id']}/consultation", json=CONSULTATION, headers=doctor)
    assert client.put("/doctors/me/call-next", headers=doctor).status_code == 404   # nobody waiting
    assert client.put("/doctors/me/call-next", headers=first).status_code == 403    # doctors only


def test_consultation_completes_appointment_and_enforces_rules(client, setup_doctor, register_patient, monkeypatch):
    doctor_id = setup_doctor()
    other_doctor = setup_doctor("doc2@test.com", "Dr Two", dept_name="Cardiology")
    patient = register_patient()
    appointment, day, doctor = to_in_consultation(client, monkeypatch, doctor_id, patient)
    url = f"/appointments/{appointment['id']}/consultation"

    assert client.post(url, json=CONSULTATION, headers=patient).status_code == 403                       # patient
    assert client.post(url, json=CONSULTATION, headers=auth(client, "doc2@test.com")).status_code == 403  # wrong doctor
    assert client.post(url, json={**CONSULTATION, "symptoms": ""}, headers=doctor).status_code == 422
    assert client.post(url, json={**CONSULTATION, "follow_up_date": day.isoformat()}, headers=doctor).status_code == 400

    follow_up = (day + timedelta(days=7)).isoformat()
    saved = client.post(url, json={**CONSULTATION, "follow_up_date": follow_up}, headers=doctor)
    assert saved.status_code == 201
    assert saved.json()["prescription"][0]["medicine"] == "Aspirin"
    assert client.post(url, json=CONSULTATION, headers=doctor).status_code == 400   # appointment is already Completed

    detail = client.get(f"/appointments/{appointment['id']}", headers=patient).json()
    assert detail["status"] == "COMPLETED"
    assert [h["new_status"] for h in detail["history"]] == ["BOOKED", "CHECKED_IN", "IN_CONSULTATION", "COMPLETED"]

    read = client.get(url, headers=patient)
    assert read.status_code == 200 and read.json()["diagnosis"] == "Mild angina"
    stranger = register_patient("s@test.com", name="Stranger", phone="9000000008")
    assert client.get(url, headers=stranger).status_code == 403


def test_consultation_requires_in_consultation_status(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    patient = register_patient()
    appointment = book(client, patient, doctor_id, future_weekday(3), "09:00").json()
    response = client.post(f"/appointments/{appointment['id']}/consultation", json=CONSULTATION, headers=auth(client, "doc@test.com"))
    assert response.status_code == 400


def test_patient_history_includes_diagnosis_and_files(client, setup_doctor, register_patient, monkeypatch):
    doctor_id = setup_doctor()
    patient = register_patient()
    appointment, _day, doctor = to_in_consultation(client, monkeypatch, doctor_id, patient)
    client.post(f"/appointments/{appointment['id']}/consultation", json=CONSULTATION, headers=doctor)
    client.post(
        f"/appointments/{appointment['id']}/files",
        files={"file": ("lab.pdf", b"%PDF-1.4 test", "application/pdf")}, headers=patient,
    )
    history = client.get("/patients/me/history", headers=patient).json()
    assert history["total"] == 1
    item = history["items"][0]
    assert item["consultation"]["diagnosis"] == "Mild angina"
    assert item["files"][0]["original_filename"] == "lab.pdf"
    assert client.get("/patients/me/history", headers=doctor).status_code == 403


def test_queue_snapshot_numbers(client, setup_doctor, register_patient, monkeypatch, admin_headers, db):
    from app.services import queue_service

    doctor_id = setup_doctor(slot=15)
    day = future_weekday(4)
    patients = [register_patient(f"p{i}@test.com", phone=f"900000000{i}") for i in range(1, 4)]
    appointments = [book(client, h, doctor_id, day, t).json() for h, t in zip(patients, ["09:00", "09:15", "09:30"])]
    freeze_now(monkeypatch, at_slot(day, "09:00", timedelta(minutes=5)))   # 09:05: check-in is open for all three
    for appointment in appointments:
        client.put(f"/appointments/{appointment['id']}/check-in", headers=admin_headers)
    client.put("/doctors/me/call-next", headers=auth(client, "doc@test.com"))

    snapshot = queue_service.build_snapshot(db, doctor_id, day)
    assert snapshot["current_token"] == 1 and snapshot["waiting_count"] == 2
    assert [e["position"] for e in snapshot["entries"]] == [1, 2]
    # wait = (people ahead + the one in consultation) * slot length
    assert [e["estimated_wait_minutes"] for e in snapshot["entries"]] == [15, 30]
    assert queue_service.build_snapshot(db, 9999) is None
