import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import auth, login, book, future_weekday, freeze_now, at_slot
from datetime import timedelta


def _token(client, email):
    return login(client, email)["access_token"]


def test_queue_socket_rejects_missing_or_invalid_token(client, setup_doctor):
    doctor_id = setup_doctor()
    for query in ("", "?token=garbage"):
        with pytest.raises(WebSocketDisconnect) as info:
            with client.websocket_connect(f"/ws/queue/{doctor_id}{query}"):
                pass
        assert info.value.code == 1008


def test_queue_socket_rejects_expired_token(client, setup_doctor, monkeypatch):
    import jwt
    from app.config import settings

    doctor_id = setup_doctor()
    expired = jwt.encode(
        {"sub": "1", "type": "access", "exp": 1000000000}, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/queue/{doctor_id}?token={expired}"):
            pass


def test_refresh_token_is_not_accepted_for_websocket(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    register_patient("p@test.com")
    refresh = login(client, "p@test.com")["refresh_token"]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/queue/{doctor_id}?token={refresh}"):
            pass


def test_unknown_doctor_is_rejected(client, register_patient):
    register_patient("p@test.com")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/queue/9999?token={_token(client, 'p@test.com')}"):
            pass


def test_queue_socket_sends_snapshot_on_connect(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    register_patient("p@test.com")
    with client.websocket_connect(f"/ws/queue/{doctor_id}?token={_token(client, 'p@test.com')}") as ws:
        message = ws.receive_json()
        assert message["type"] == "queue_update"
        assert message["doctor_id"] == doctor_id
        assert message["waiting_count"] == 0 and message["current_token"] is None
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_notification_socket_connects_with_valid_token(client, register_patient):
    register_patient("p@test.com")
    with client.websocket_connect(f"/ws/notifications?token={_token(client, 'p@test.com')}") as ws:
        assert ws.receive_json()["type"] == "connected"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/notifications?token=bad"):
            pass


def test_booking_sends_personal_notification(client, setup_doctor, register_patient):
    doctor_id = setup_doctor()
    patient = register_patient("p@test.com")
    with client.websocket_connect(f"/ws/notifications?token={_token(client, 'p@test.com')}") as ws:
        ws.receive_json()  # "connected"
        assert book(client, patient, doctor_id, future_weekday(3), "09:00").status_code == 201
        message = ws.receive_json()
        assert message["type"] == "notification" and message["event"] == "appointment_booked"


def test_check_in_broadcasts_queue_update_to_connected_clients(client, setup_doctor, register_patient, admin_headers, monkeypatch):
    doctor_id = setup_doctor()
    patient = register_patient("p@test.com")
    day = future_weekday(3)
    appointment = book(client, patient, doctor_id, day, "10:00").json()
    freeze_now(monkeypatch, at_slot(day, "10:00", timedelta(minutes=-5)))   # "today" is the appointment day

    with client.websocket_connect(f"/ws/queue/{doctor_id}?token={_token(client, 'p@test.com')}") as ws:
        first = ws.receive_json()
        assert first["waiting_count"] == 0
        assert client.put(f"/appointments/{appointment['id']}/check-in", headers=admin_headers).status_code == 200
        update = ws.receive_json()
        assert update["type"] == "queue_update" and update["waiting_count"] == 1
        assert update["your_token"] == 1 and update["your_queue_position"] == 1
