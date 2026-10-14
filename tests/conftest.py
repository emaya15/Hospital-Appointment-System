"""Test configuration.

Tests run against an in-memory SQLite database, NEVER your MySQL database.
The environment variables below are set BEFORE the app is imported.
"""

import os
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="hospital_tests_")
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-automated-tests-only"
os.environ["MAIL_MODE"] = "mock"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["UPLOAD_DIR"] = str(Path(_TMP) / "uploads")
os.environ["PDF_DIR"] = str(Path(_TMP) / "pdfs")
os.environ["TIMEZONE"] = "Asia/Kolkata"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402,F401
from app.auth.security import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Doctor, Department, Role, User  # noqa: E402
from app.services import email_service  # noqa: E402
from app.utils import clock  # noqa: E402

PASSWORD = "Passw0rd123"


@pytest.fixture(autouse=True)
def clean_storage():
    """Every test starts with empty upload and PDF folders."""
    import shutil
    from app.config import settings

    for folder in (settings.UPLOAD_DIR, settings.PDF_DIR):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture(autouse=True)
def fresh_database():
    """Tables are created for tests only (the real app uses Alembic migrations)."""
    Base.metadata.create_all(engine)
    email_service.sent_mock_emails.clear()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db():
    with SessionLocal() as session:
        yield session


def future_weekday(days_ahead: int = 3) -> date:
    """A date at least ``days_ahead`` days from today (always in the future)."""
    return clock.today() + timedelta(days=days_ahead)


def login(client, email: str, password: str = PASSWORD) -> dict:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth(client, email: str) -> dict:
    return {"Authorization": f"Bearer {login(client, email)['access_token']}"}


def make_user(db, email: str, role: Role, name: str = "Test User", phone: str = "9876543210") -> User:
    user = User(email=email, hashed_password=hash_password(PASSWORD), full_name=name, phone=phone, role=role)
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def admin_headers(client, db):
    make_user(db, "admin@test.com", Role.ADMIN, "Admin")
    return auth(client, "admin@test.com")


@pytest.fixture()
def setup_doctor(client, admin_headers):
    """Create department + doctor (via the API) with a schedule for every weekday."""

    def _create(email="doc@test.com", name="Dr. House", slot=30, fee=500, dept_name="Cardiology"):
        dept = client.post("/departments", json={"name": dept_name}, headers=admin_headers)
        dept_id = dept.json()["id"] if dept.status_code == 201 else client.get(
            "/departments", headers=admin_headers
        ).json()["items"][0]["id"]
        user = client.post(
            "/auth/users",
            json={"email": email, "password": PASSWORD, "full_name": name, "phone": "9123456780", "role": "DOCTOR"},
            headers=admin_headers,
        )
        assert user.status_code == 201, user.text
        doctor = client.post(
            "/doctors",
            json={
                "user_id": user.json()["id"],
                "department_id": dept_id,
                "specialization": "Cardiologist",
                "qualification": "MD",
                "experience_years": 10,
                "consultation_fee": fee,
                "slot_duration_minutes": slot,
            },
            headers=admin_headers,
        )
        assert doctor.status_code == 201, doctor.text
        doctor_id = doctor.json()["id"]
        for weekday in range(7):
            response = client.post(
                f"/doctors/{doctor_id}/schedules",
                json={
                    "day_of_week": weekday,
                    "start_time": "09:00:00",
                    "end_time": "13:00:00",
                    "break_start": "11:00:00",
                    "break_end": "11:30:00",
                },
                headers=admin_headers,
            )
            assert response.status_code == 201, response.text
        return doctor_id

    return _create


@pytest.fixture()
def register_patient(client):
    def _register(email="pat@test.com", name="Pat Ient", phone="9000000001"):
        response = client.post(
            "/auth/register",
            json={"email": email, "password": PASSWORD, "full_name": name, "phone": phone},
        )
        assert response.status_code == 201, response.text
        return auth(client, email)

    return _register


def book(client, headers, doctor_id, day, at="09:00", reason="Chest pain"):
    return client.post(
        "/appointments",
        json={"doctor_id": doctor_id, "appointment_date": day.isoformat(), "appointment_time": at, "reason": reason},
        headers=headers,
    )


def freeze_now(monkeypatch, moment: datetime) -> None:
    """Pretend the current time is ``moment`` (timezone-aware)."""
    monkeypatch.setattr(clock, "now", lambda: moment)
    monkeypatch.setattr(clock, "today", lambda: moment.date())


def at_slot(day: date, hhmm: str, delta: timedelta = timedelta(0)) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return clock.slot_datetime(day, time(hour, minute)) + delta


def to_in_consultation(client, monkeypatch, doctor_id, patient_headers, doctor_email="doc@test.com", at="10:00", days=4):
    """Book -> check-in (time frozen 10 minutes before the slot) -> doctor calls the patient.

    Returns (appointment_json, day, doctor_headers). Time stays frozen on the appointment day.
    """
    day = future_weekday(days)
    appointment = book(client, patient_headers, doctor_id, day, at).json()
    freeze_now(monkeypatch, at_slot(day, at, timedelta(minutes=-10)))
    admin = auth(client, "admin@test.com")
    assert client.put(f"/appointments/{appointment['id']}/check-in", headers=admin).status_code == 200
    doctor_headers = auth(client, doctor_email)
    called = client.put("/doctors/me/call-next", headers=doctor_headers)
    assert called.status_code == 200, called.text
    return appointment, day, doctor_headers
