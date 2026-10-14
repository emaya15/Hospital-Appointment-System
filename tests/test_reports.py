from datetime import timedelta

from app.models import Appointment, AppointmentStatus, Patient, User, Role
from app.utils import clock
from tests.conftest import make_user

S = AppointmentStatus


def _patient(db, email):
    user = make_user(db, email, Role.PATIENT, email.split("@")[0])
    patient = Patient(user_id=user.id)
    db.add(patient)
    db.commit()
    return patient


def _appt(db, patient, doctor_id, day, at, status, fee=500, number=None):
    from datetime import time
    hour, minute = map(int, at.split(":"))
    appt = Appointment(
        appointment_number=number or f"APT-T-{patient.id}-{doctor_id}-{day.toordinal()}-{at}",
        patient_id=patient.id, doctor_id=doctor_id, appointment_date=day, appointment_time=time(hour, minute),
        token_number=1, reason="test", status=status, consultation_fee=fee,
        slot_active=None if status == S.CANCELLED else 1,
    )
    db.add(appt)
    db.commit()
    return appt


def test_reports_are_admin_only(client, register_patient):
    patient = register_patient()
    for path in ("dashboard", "doctor-performance", "department-summary", "peak-hours", "frequent-no-shows"):
        assert client.get(f"/reports/{path}", headers=patient).status_code == 403
        assert client.get(f"/reports/{path}").status_code == 401


def test_reports_with_no_data_return_zeros(client, admin_headers):
    dash = client.get("/reports/dashboard", headers=admin_headers).json()
    assert dash["total_appointments"] == 0 and dash["revenue"] == 0
    peak = client.get("/reports/peak-hours", headers=admin_headers).json()
    assert peak["hours"] == [] and peak["busiest_hour"] is None
    assert client.get("/reports/doctor-performance", headers=admin_headers).json()["items"] == []
    assert client.get("/reports/frequent-no-shows", headers=admin_headers).json()["items"] == []


def test_dashboard_counts_and_revenue(client, admin_headers, setup_doctor, db):
    doctor_id = setup_doctor()
    today = clock.today()
    for index, status in enumerate([S.BOOKED, S.CHECKED_IN, S.COMPLETED, S.COMPLETED, S.CANCELLED, S.NO_SHOW]):
        patient = _patient(db, f"p{index}@test.com")
        _appt(db, patient, doctor_id, today, f"1{index}:00", status, fee=400)
    dash = client.get("/reports/dashboard", headers=admin_headers).json()
    assert dash["total_appointments"] == 6
    assert (dash["booked"], dash["checked_in"], dash["completed"], dash["cancelled"], dash["no_show"]) == (1, 1, 2, 1, 1)
    assert dash["revenue"] == 800.0     # only completed consultations count


def test_doctor_performance_and_department_summary(client, admin_headers, setup_doctor, db):
    doctor_id = setup_doctor()
    today = clock.today()
    plan = [S.COMPLETED, S.COMPLETED, S.NO_SHOW, S.CANCELLED]
    for index, status in enumerate(plan):
        _appt(db, _patient(db, f"q{index}@test.com"), doctor_id, today - timedelta(days=index + 1), "09:00", status, fee=500)

    report = client.get("/reports/doctor-performance", headers=admin_headers).json()
    row = report["items"][0]
    assert row["total_appointments"] == 4 and row["completed_consultations"] == 2
    assert row["no_shows"] == 1 and row["cancelled"] == 1
    assert row["revenue"] == 1000.0
    assert row["no_show_percentage"] == 33.33          # 1 no-show out of 3 expected visits (cancelled excluded)

    narrow = client.get(
        f"/reports/doctor-performance?date_from={today}&date_to={today}", headers=admin_headers
    ).json()["items"][0]
    assert narrow["total_appointments"] == 0 and narrow["no_show_percentage"] == 0.0

    summary = client.get("/reports/department-summary", headers=admin_headers).json()["items"][0]
    assert summary["department_name"] == "Cardiology" and summary["total_appointments"] == 4


def test_date_range_validation(client, admin_headers):
    assert client.get("/reports/doctor-performance?date_from=2030-02-01&date_to=2030-01-01", headers=admin_headers).status_code == 400
    assert client.get("/reports/peak-hours?date_from=2020-01-01&date_to=2030-01-01", headers=admin_headers).status_code == 400
    assert client.get("/reports/peak-hours?date_from=notadate", headers=admin_headers).status_code == 422


def test_peak_hours_counts_per_hour(client, admin_headers, setup_doctor, db):
    doctor_id = setup_doctor()
    today = clock.today()
    for index, at in enumerate(["09:00", "09:30", "09:45", "10:00"]):
        _appt(db, _patient(db, f"h{index}@test.com"), doctor_id, today, at, S.BOOKED)
    _appt(db, _patient(db, "cancelled@test.com"), doctor_id, today, "12:00", S.CANCELLED)
    report = client.get("/reports/peak-hours", headers=admin_headers).json()
    assert {h["hour"]: h["appointments"] for h in report["hours"]} == {9: 3, 10: 1}
    assert report["busiest_hour"] == 9


def test_frequent_no_shows_needs_three_in_90_days(client, admin_headers, setup_doctor, db):
    doctor_id = setup_doctor()
    today = clock.today()
    repeat = _patient(db, "repeat@test.com")
    occasional = _patient(db, "occasional@test.com")
    old = _patient(db, "old@test.com")
    # each patient gets their own time of day, because one doctor cannot have two appointments in the same slot
    for days in (5, 20, 40):
        _appt(db, repeat, doctor_id, today - timedelta(days=days), "09:00", S.NO_SHOW)
    for days in (5, 20):
        _appt(db, occasional, doctor_id, today - timedelta(days=days), "09:30", S.NO_SHOW)
    for days in (100, 110, 120):
        _appt(db, old, doctor_id, today - timedelta(days=days), "10:00", S.NO_SHOW)

    items = client.get("/reports/frequent-no-shows", headers=admin_headers).json()["items"]
    assert [i["email"] for i in items] == ["repeat@test.com"]
    assert items[0]["no_show_count"] == 3
