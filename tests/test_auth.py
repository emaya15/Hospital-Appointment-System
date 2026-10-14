import jwt
from app.config import settings
from app.models import Role
from tests.conftest import PASSWORD, auth, login, make_user


def test_register_creates_patient_and_rejects_duplicate_email(client):
    payload = {"email": "A@Test.com", "password": PASSWORD, "full_name": "Anu", "phone": "9876543210"}
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201
    assert response.json()["role"] == "PATIENT"
    assert response.json()["email"] == "a@test.com"
    assert client.post("/auth/register", json=payload).status_code == 409


def test_register_cannot_choose_role(client):
    payload = {"email": "x@test.com", "password": PASSWORD, "full_name": "Xan", "phone": "9876543210", "role": "ADMIN"}
    assert client.post("/auth/register", json=payload).json()["role"] == "PATIENT"


def test_register_validation_errors(client):
    base = {"email": "v@test.com", "password": PASSWORD, "full_name": "Vee", "phone": "9876543210"}
    assert client.post("/auth/register", json={**base, "phone": "12345"}).status_code == 422
    assert client.post("/auth/register", json={**base, "phone": "98765abcde"}).status_code == 422
    assert client.post("/auth/register", json={**base, "password": "short1"}).status_code == 422
    assert client.post("/auth/register", json={**base, "email": "not-an-email"}).status_code == 422
    assert client.post("/auth/register", json={"email": "v@test.com"}).status_code == 422


def test_login_success_and_wrong_password(client, register_patient):
    register_patient("p@test.com")
    tokens = login(client, "p@test.com")
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 30 * 60
    bad = client.post("/auth/login", json={"email": "p@test.com", "password": "wrongpass1"})
    assert bad.status_code == 401


def test_access_token_lifetime_is_30_minutes_and_refresh_7_days(client, register_patient):
    register_patient("p@test.com")
    tokens = login(client, "p@test.com")
    options = {"verify_signature": False}
    access = jwt.decode(tokens["access_token"], options=options)
    refresh = jwt.decode(tokens["refresh_token"], options=options)
    assert round((access["exp"] - __import__("time").time()) / 60) in (29, 30)
    assert round((refresh["exp"] - __import__("time").time()) / 86400) in (6, 7)
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 30 and settings.REFRESH_TOKEN_EXPIRE_DAYS == 7


def test_inactive_user_cannot_login(client, db):
    user = make_user(db, "off@test.com", Role.PATIENT)
    user.is_active = False
    db.commit()
    response = client.post("/auth/login", json={"email": "off@test.com", "password": PASSWORD})
    assert response.status_code == 403


def test_me_requires_valid_token(client, register_patient):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    headers = register_patient("p@test.com")
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["patient_id"] is not None


def test_refresh_token_rotation_and_logout_revocation(client, register_patient):
    register_patient("p@test.com")
    tokens = login(client, "p@test.com")

    refreshed = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    new = refreshed.json()
    # the old refresh token was revoked by the rotation
    assert client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401

    headers = {"Authorization": f"Bearer {new['access_token']}"}
    assert client.post("/auth/logout", json={"refresh_token": new["refresh_token"]}, headers=headers).status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401


def test_access_token_cannot_be_used_as_refresh_token(client, register_patient):
    register_patient("p@test.com")
    tokens = login(client, "p@test.com")
    assert client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401


def test_only_admin_can_create_doctor_or_admin_accounts(client, register_patient, admin_headers):
    body = {"email": "d@test.com", "password": PASSWORD, "full_name": "Doc", "phone": "9876543210", "role": "DOCTOR"}
    assert client.post("/auth/users", json=body).status_code == 401
    assert client.post("/auth/users", json=body, headers=register_patient("p@test.com")).status_code == 403
    assert client.post("/auth/users", json=body, headers=admin_headers).status_code == 201
    assert client.post("/auth/users", json={**body, "role": "PATIENT"}, headers=admin_headers).status_code == 422


def test_default_admin_is_created_on_startup_once(client, db, monkeypatch):
    from sqlalchemy import select, func
    from app.config import settings
    from app.models import User
    from app.services import auth_service

    monkeypatch.setattr(settings, "FIRST_ADMIN_EMAIL", "boss@hospital.org")
    monkeypatch.setattr(settings, "FIRST_ADMIN_PASSWORD", "BossPass123")
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", "9999999999")

    assert auth_service.seed_default_admin(db) is True
    assert auth_service.seed_default_admin(db) is False        # second start: nothing duplicated
    assert db.scalar(select(func.count()).select_from(User).where(User.email == "boss@hospital.org")) == 1
    db.commit()  # end this session's transaction before the API call below uses the same SQLite connection

    tokens = login(client, "boss@hospital.org", "BossPass123")
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json()
    assert me["role"] == "ADMIN"


def test_default_admin_skipped_when_not_configured(db, monkeypatch):
    from app.config import settings
    from app.services import auth_service

    monkeypatch.setattr(settings, "FIRST_ADMIN_EMAIL", "")
    assert auth_service.seed_default_admin(db) is False
