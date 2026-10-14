from tests.conftest import auth, book, future_weekday


def test_schedule_validation(client, admin_headers, setup_doctor):
    doctor_id = setup_doctor()
    url = f"/doctors/{doctor_id}/schedules"
    base = {"day_of_week": 0, "start_time": "09:00:00", "end_time": "13:00:00"}

    assert client.post(url, json={**base, "start_time": "14:00:00"}, headers=admin_headers).status_code == 400
    assert client.post(url, json={**base, "day_of_week": 9}, headers=admin_headers).status_code == 422
    # overlaps the schedule created by the fixture
    assert client.post(url, json={**base, "start_time": "12:00:00", "end_time": "15:00:00"}, headers=admin_headers).status_code == 409
    # break outside the working hours, or only half a break -> 400 (validated before the overlap check)
    outside = {**base, "break_start": "08:00:00", "break_end": "08:30:00"}
    assert client.post(url, json=outside, headers=admin_headers).status_code == 400
    half = {**base, "break_start": "10:00:00"}
    assert client.post(url, json=half, headers=admin_headers).status_code == 400


def test_available_slots_exclude_break_booked_and_leave(client, admin_headers, setup_doctor, register_patient):
    doctor_id = setup_doctor(slot=30)
    day = future_weekday(5)
    slots = client.get(f"/doctors/{doctor_id}/available-slots?date={day}", headers=admin_headers).json()["slots"]
    assert slots == ["09:00", "09:30", "10:00", "10:30", "11:30", "12:00", "12:30"]  # 11:00 is the break

    assert book(client, register_patient(), doctor_id, day, "09:30").status_code == 201
    slots = client.get(f"/doctors/{doctor_id}/available-slots?date={day}", headers=admin_headers).json()["slots"]
    assert "09:30" not in slots

    leave = client.post(
        f"/doctors/{doctor_id}/leaves",
        json={"start_date": day.isoformat(), "end_date": day.isoformat()},
        headers=admin_headers,
    )
    assert leave.status_code == 201
    slots = client.get(f"/doctors/{doctor_id}/available-slots?date={day}", headers=admin_headers).json()["slots"]
    assert slots == []


def test_doctor_manages_only_own_schedule(client, setup_doctor):
    mine = setup_doctor("me@test.com", "Dr Me")
    other = setup_doctor("other@test.com", "Dr Other", dept_name="Cardiology")
    headers = auth(client, "me@test.com")
    body = {"day_of_week": 0, "start_time": "15:00:00", "end_time": "17:00:00"}
    assert client.post(f"/doctors/{other}/schedules", json=body, headers=headers).status_code == 403
    assert client.post(f"/doctors/{mine}/schedules", json=body, headers=headers).status_code == 201
    assert client.post(
        f"/doctors/{other}/leaves",
        json={"start_date": future_weekday(9).isoformat(), "end_date": future_weekday(9).isoformat()},
        headers=headers,
    ).status_code == 403


def test_leave_cancels_appointments_and_sends_email(client, admin_headers, setup_doctor, register_patient):
    from app.services import email_service

    doctor_id = setup_doctor()
    patient = register_patient()
    day = future_weekday(6)
    appointment = book(client, patient, doctor_id, day, "10:00").json()
    email_service.sent_mock_emails.clear()

    response = client.post(
        f"/doctors/{doctor_id}/leaves",
        json={"start_date": day.isoformat(), "end_date": day.isoformat(), "reason": "Conference"},
        headers=admin_headers,
    )
    assert response.status_code == 201 and response.json()["cancelled_appointments"] == 1

    detail = client.get(f"/appointments/{appointment['id']}", headers=patient).json()
    assert detail["status"] == "CANCELLED"
    assert detail["history"][-1]["new_status"] == "CANCELLED"
    assert any("leave" in m.subject.lower() for m in email_service.sent_mock_emails)
    # overlapping leave is rejected
    assert client.post(
        f"/doctors/{doctor_id}/leaves",
        json={"start_date": day.isoformat(), "end_date": day.isoformat()},
        headers=admin_headers,
    ).status_code == 409
