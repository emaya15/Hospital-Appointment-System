"""WebSocket endpoints.

* WS /ws/queue/{doctor_id}?token=<access token>   live queue of one doctor
* WS /ws/notifications?token=<access token>        personal notifications

The access token is passed as a query parameter because browsers cannot set headers
on WebSocket connections. Invalid or expired tokens are rejected before the
connection is accepted.
"""

import logging

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.auth.security import user_from_access_token
from app.database import SessionLocal
from app.models.doctor import Doctor
from app.utils.exceptions import AppError
from app.websockets.manager import ClientInfo, manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _authenticate(token: str | None) -> ClientInfo | None:
    """Validate the token (runs in a worker thread). None means: reject."""
    if not token:
        return None
    try:
        with SessionLocal() as db:
            user = user_from_access_token(db, token)
            return ClientInfo(user_id=user.id, role=user.role)
    except AppError:
        return None


def _doctor_exists(doctor_id: int) -> bool:
    with SessionLocal() as db:
        return db.get(Doctor, doctor_id) is not None


async def _listen(websocket: WebSocket) -> None:
    """Keep the connection open. Answers "ping" with "pong"; ignores other messages."""
    while True:
        message = await websocket.receive_text()
        if message.strip().lower() == "ping":
            await websocket.send_text("pong")


@router.websocket("/ws/queue/{doctor_id}")
async def queue_socket(websocket: WebSocket, doctor_id: int, token: str | None = None):
    info = await anyio.to_thread.run_sync(_authenticate, token)
    if info is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not await anyio.to_thread.run_sync(_doctor_exists, doctor_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect_queue(websocket, doctor_id, info)
    try:
        await manager.send_snapshot_to(websocket, doctor_id, info)
        await _listen(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_queue(websocket, doctor_id)


@router.websocket("/ws/notifications")
async def notifications_socket(websocket: WebSocket, token: str | None = None):
    info = await anyio.to_thread.run_sync(_authenticate, token)
    if info is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect_user(websocket, info.user_id)
    try:
        await websocket.send_json(
            {"type": "connected", "message": "Notifications connected", "user_id": info.user_id}
        )
        await _listen(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_user(websocket, info.user_id)
