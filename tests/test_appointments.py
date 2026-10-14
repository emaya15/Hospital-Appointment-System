from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Appointment, AppointmentStatus
from app.services import email_service
from tests.conftest import at_slot, auth, book, freeze_now, future_weekday


def test_booking_success_copies_fee_and_creates_number_and_history(client, setup_doctor, register_patient, admin_headers):
    doctor_id = setup_doctor(fee=750)
    patient = register_patient()
    day = future_weekday(3)
    response = book(client, patient, doctor_id, day, "09:00")
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["appointment_number"] == f"APT-{day.strftime('%Y%m%d')}-0001"
    assert data["status"] == "BOOKED" and data["token_number"] == 1 and data["consultation_fee"] == 750.0

    # changing the fee later does not change the booked appointment
    client.put(f"/doctors/{doctor_id}", json={"consultation_fee": 900}, headers=admin_headers)
    assert client.get(f"/appointments/{data['id']}", headers=patient).json()["consultation_fee"] == 750.0

    history = client.get(f"/appointments/{data['id']}", headers=patient).json()["history"]
    assert [h["new_status"] for h in history] == ["BOOKED"]
    assert any("confirmed" in m.subject.lower() for m in email_service.sent_mock_emails)


def test_tokens_follow_slot_time_order(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    day = future_weekday(3)
    late = register_patient("late@test.com", phone="9000000002")
    early = register_patient("early@test.com", phone="9000000003")
    a = book(client, late, doctor_id, day, "12:00").json()
    b = book(client, early, doctor_id, day, "09:00").json()
    assert b["token_number"] == 1
    assert client.get(f"/appointments/{a['id']}", headers=late).json()["token_number"] == 2


def test_double_booking_returns_409(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    day = future_weekday(3)
    assert book(client, register_patient("a@test.com", phone="9000000002"), doctor_id, day, "09:00").status_code == 201
    second = book(client, register_patient("b@test.com", phone="9000000003"), doctor_id, day, "09:00")
    assert second.status_code == 409


def test_database_unique_constraint_blocks_duplicate_slot(client, setup_doctor, register_patient, db):
    doctor_id = setup_doctor()
    patient = register_patient()
    day = future_weekday(3)
    first = book(client, patient, doctor_id, day, "09:00").json()
    original = db.get(Appointment, first["id"])
    clone = Appointment(
        appointment_number="APT-DUPLICATE-0001", patient_id=original.patient_id + 1, doctor_id=doctor_id,
        appointment_date=day, appointment_time=original.appointment_time, token_number=9, reason="dup",
        status=AppointmentStatus.BOOKED, consultation_fee=1, slot_active=1,
    )
    db.add(clone)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_patient_rules_one_per_doctor_per_day_and_no_time_clash(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    other_doctor = setup_doctor("doc2@test.com", "Dr Two", dept_name="Cardiology")
    patient = register_patient()
    day = future_weekday(3)
    assert book(client, patient, doctor_id, day, "09:00").status_code == 201
    assert book(client, patient, doctor_id, day, "09:30").status_code == 409        # same doctor, same day
    assert book(client, patient, other_doctor, day, "09:00").status_code == 409     # same time, other doctor
    assert book(client, patient, other_doctor, day, "09:30").status_code == 201     # different doctor + time


def test_booking_window_and_schedule_rules(client, setup_doctor, register_patient, admin_headers):
    doctor_id = setup_doctor()
    patient = register_patient()
    assert book(client, patient, doctor_id, future_weekday(-1)).status_code == 400   # past
    assert book(client, patient, doctor_id, future_weekday(31)).status_code == 400   # more than 30 days
    assert book(client, patient, doctor_id, future_weekday(3), "11:00").status_code == 400  # during break
    assert book(client, patient, doctor_id, future_weekday(3), "07:00").status_code == 400  # outside hours
    assert book(client, patient, doctor_id, future_weekday(3), "09:10").status_code == 400  # not a slot boundary
    assert book(client, patient, 9999, future_weekday(3)).status_code == 404
    assert book(client, admin_headers, doctor_id, future_weekday(3)).status_code == 403      # patients only
    assert book(client, patient, doctor_id, future_weekday(30), "09:00").status_code == 201  # exactly 30 days is ok


def test_cancel_releases_slot_and_records_history(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    patient = register_patient()
    day = future_weekday(3)
    appointment = book(client, patient, doctor_id, day, "09:00").json()
    cancelled = client.put(f"/appointments/{appointment['id']}/cancel", json={"reason": "Busy"}, headers=patient)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    assert client.put(f"/appointments/{appointment['id']}/cancel", headers=patient).status_code == 400  # already cancelled

    other = register_patient("o@test.com", phone="9000000009")
    assert book(client, other, doctor_id, day, "09:00").status_code == 201   # slot is free again
    history = client.get(f"/appointments/{appointment['id']}", headers=patient).json()["history"]
    assert history[-1]["old_status"] == "BOOKED" and history[-1]["new_status"] == "CANCELLED"


def test_cancel_and_reschedule_need_two_hours_notice(client, setup_doctor, register_patient, monkeypatch):
    doctor_id = setup_doctor()
    patient = register_patient()
    day = future_weekday(3)
    appointment = book(client, patient, doctor_id, day, "10:00").json()

    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(minutes=-90)))   # only 1.5 h left
    assert client.put(f"/appointments/{appointment['id']}/cancel", headers=patient).status_code == 400
    body = {"new_date": day.isoformat(), "new_time": "12:00"}
    assert client.put(f"/appointments/{appointment['id']}/reschedule", json=body, headers=patient).status_code == 400

    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(minutes=-130)))  # 2h10 left
    assert client.put(f"/appointments/{appointment['id']}/reschedule", json=body, headers=patient).status_code == 200


def test_reschedule_limit_and_ownership(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    patient = register_patient()
    stranger = register_patient("s@test.com", phone="9000000008")
    day = future_weekday(3)
    appointment = book(client, patient, doctor_id, day, "09:00").json()
    url = f"/appointments/{appointment['id']}/reschedule"

    assert client.put(url, json={"new_date": day.isoformat(), "new_time": "09:30"}, headers=stranger).status_code == 403
    assert client.put(url, json={"new_date": day.isoformat(), "new_time": "09:30"}, headers=patient).json()["reschedule_count"] == 1
    assert client.put(url, json={"new_date": day.isoformat(), "new_time": "10:00"}, headers=patient).json()["reschedule_count"] == 2
    third = client.put(url, json={"new_date": day.isoformat(), "new_time": "10:30"}, headers=patient)
    assert third.status_code == 400 and "at most 2" in third.json()["detail"]

    # the first slot was released by the reschedule
    other = register_patient("o@test.com", phone="9000000009")
    assert book(client, other, doctor_id, day, "09:00").status_code == 201


def test_reschedule_into_taken_slot_is_409(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    day = future_weekday(3)
    first = register_patient("a@test.com", phone="9000000002")
    second = register_patient("b@test.com", phone="9000000003")
    book(client, first, doctor_id, day, "09:00")
    appointment = book(client, second, doctor_id, day, "09:30").json()
    response = client.put(
        f"/appointments/{appointment['id']}/reschedule",
        json={"new_date": day.isoformat(), "new_time": "09:00"}, headers=second,
    )
    assert response.status_code == 409


def test_check_in_window_and_roles(client, setup_doctor, register_patient, admin_headers, monkeypatch):
    doctor_id = setup_doctor()
    patient = register_patient()
    day = future_weekday(3)
    appointment = book(client, patient, doctor_id, day, "10:00").json()
    url = f"/appointments/{appointment['id']}/check-in"

    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(minutes=-31)))
    assert client.put(url, headers=admin_headers).status_code == 400      # too early
    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(days=-1)))
    assert client.put(url, headers=admin_headers).status_code == 400      # wrong day
    assert client.put(url, headers=auth(client, "doc@test.com")).status_code == 403   # doctors do not check in
    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(minutes=-30)))
    ok = client.put(url, headers=admin_headers)
    assert ok.status_code == 200 and ok.json()["status"] == "CHECKED_IN"
    assert client.put(url, headers=admin_headers).status_code == 400      # only BOOKED can check in


def test_no_show_job_marks_late_appointments(client, setup_doctor, register_patient, monkeypatch, db):
    from app.jobs.scheduler import detect_no_shows

    doctor_id = setup_doctor()
    patient = register_patient()
    day = future_weekday(3)
    appointment = book(client, patient, doctor_id, day, "10:00").json()

    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(minutes=10)))   # inside the grace period
    assert detect_no_shows() == 0
    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(minutes=16)))
    assert detect_no_shows() == 1
    assert detect_no_shows() == 0                                            # idempotent
    detail = client.get(f"/appointments/{appointment['id']}", headers=patient).json()
    assert detail["status"] == "NO_SHOW"
    assert detail["history"][-1]["new_status"] == "NO_SHOW"
    # a no-show cannot be cancelled or checked in
    assert client.put(f"/appointments/{appointment['id']}/cancel", headers=patient).status_code == 400


def test_listing_filters_and_pagination(client, setup_doctor, register_patient, admin_headers):
    doctor_id = setup_doctor()
    patient = register_patient()
    for offset, at in [(3, "09:00"), (4, "09:00"), (5, "09:00")]:
        book(client, patient, doctor_id, future_weekday(offset), at)

    assert client.get("/appointments?limit=2", headers=patient).json()["total"] == 3
    assert len(client.get("/appointments?limit=2", headers=patient).json()["items"]) == 2
    assert len(client.get("/appointments?skip=2&limit=2", headers=patient).json()["items"]) == 1
    day = future_weekday(4).isoformat()
    assert client.get(f"/appointments?date_from={day}&date_to={day}", headers=admin_headers).json()["total"] == 1
    assert client.get("/appointments?status=CANCELLED", headers=admin_headers).json()["total"] == 0
    assert client.get(f"/appointments?doctor_id={doctor_id}", headers=admin_headers).json()["total"] == 3
    number = client.get("/appointments", headers=patient).json()["items"][0]["appointment_number"]
    assert client.get(f"/appointments?appointment_number={number}", headers=admin_headers).json()["total"] == 1
    assert client.get(f"/appointments?date_from=2030-02-01&date_to=2030-01-01", headers=admin_headers).status_code == 400
    assert client.get("/appointments?limit=1000", headers=patient).status_code == 422

    # patients never see other patients' appointments
    stranger = register_patient("s@test.com", phone="9000000008")
    assert client.get("/appointments", headers=stranger).json()["total"] == 0
    first_id = client.get("/appointments", headers=patient).json()["items"][0]["id"]
    assert client.get(f"/appointments/{first_id}", headers=stranger).status_code == 403
    assert client.get("/appointments/99999", headers=patient).status_code == 404
