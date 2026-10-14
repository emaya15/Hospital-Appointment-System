from tests.conftest import auth


def test_unauthenticated_requests_get_401(client):
    for method, path in [("get", "/appointments"), ("get", "/doctors"), ("get", "/departments"), ("get", "/patients/me/history")]:
        response = getattr(client, method)(path)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer"


def test_wrong_role_gets_403(client, register_patient, setup_doctor):
    setup_doctor()
    patient = register_patient()
    doctor = auth(client, "doc@test.com")
    assert client.put("/doctors/me/call-next", headers=patient).status_code == 403
    assert client.get("/patients/me/history", headers=doctor).status_code == 403
    assert client.post("/appointments", json={"doctor_id": 1, "appointment_date": "2030-01-01", "appointment_time": "09:00", "reason": "abc"}, headers=doctor).status_code == 403


def test_validation_errors_are_clean_422(client, register_patient):
    patient = register_patient()
    response = client.post("/appointments", json={"doctor_id": "x"}, headers=patient)
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "Validation error" and isinstance(body["errors"], list)
    assert "input" not in str(body)          # the submitted values are not echoed back


def test_not_found_and_pagination_limits(client, register_patient):
    patient = register_patient()
    assert client.get("/doctors/424242", headers=patient).status_code == 404
    assert client.get("/doctors?skip=-1", headers=patient).status_code == 422
    assert client.get("/doctors?limit=0", headers=patient).status_code == 422


def test_unexpected_errors_are_hidden(client, register_patient, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import department_service

    patient = register_patient()

    def boom(*_args, **_kwargs):
        raise RuntimeError("secret database password is hunter2")

    monkeypatch.setattr(department_service, "list_departments", boom)
    with TestClient(app, raise_server_exceptions=False) as safe_client:
        response = safe_client.get("/departments", headers=patient)
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


def test_queue_test_page_and_health(client):
    page = client.get("/queue-test")
    assert page.status_code == 200 and "Doctor ID" in page.text
    assert client.get("/health").json() == {"status": "ok"}
