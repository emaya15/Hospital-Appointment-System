"""WebSocket connection manager.

Two kinds of connections are tracked:

* queue connections   - ``/ws/queue/{doctor_id}``: live queue for one doctor
* personal connections - ``/ws/notifications``: messages for one user

Normal (synchronous) route handlers and background jobs run in other threads, so
they call ``manager.schedule(...)`` which hands the work to the server's event loop.
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass

import anyio
from fastapi import WebSocket

from app.models.enums import Role

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClientInfo:
    user_id: int
    role: Role


def _load_snapshot(doctor_id: int) -> dict | None:
    """Read the queue from the database (runs in a worker thread)."""
    # Imported here to avoid circular imports (services import websocket events).
    from app.database import SessionLocal
    from app.services import queue_service

    with SessionLocal() as db:
        return queue_service.build_snapshot(db, doctor_id)


def personalize(snapshot: dict, info: ClientInfo) -> dict:
    """Build the message one client receives from the shared queue snapshot."""
    message = {
        "type": "queue_update",
        "doctor_id": snapshot["doctor_id"],
        "date": snapshot["date"],
        "current_token": snapshot["current_token"],
        "waiting_count": snapshot["waiting_count"],
        "waiting_tokens": [entry["token_number"] for entry in snapshot["entries"]],
    }
    if info.role == Role.PATIENT:
        mine = next((e for e in snapshot["entries"] if e["patient_user_id"] == info.user_id), None)
        if mine is not None:
            message["your_token"] = mine["token_number"]
            message["your_queue_position"] = mine["position"]
            message["estimated_wait_minutes"] = mine["estimated_wait_minutes"]
        elif snapshot.get("current_patient_user_id") == info.user_id:
            message["your_token"] = snapshot["current_token"]
            message["your_queue_position"] = 0
            message["estimated_wait_minutes"] = 0
            message["status"] = "It is your turn"
    return message


class ConnectionManager:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue_clients: dict[int, dict[WebSocket, ClientInfo]] = defaultdict(dict)
        self.user_clients: dict[int, set[WebSocket]] = defaultdict(set)
        # doctor_id -> appointment ids that already received "You are next"
        self._notified_next: dict[int, set[int]] = defaultdict(set)

    # -- event loop bridge --------------------------------------------------
    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def schedule(self, coroutine) -> None:
        """Run a coroutine on the server event loop from any thread (fire and forget)."""
        loop = self.loop
        if loop is None or loop.is_closed():
            coroutine.close()
            return
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        future.add_done_callback(self._log_failure)

    @staticmethod
    def _log_failure(future) -> None:
        try:
            future.result()
        except Exception:  # noqa: BLE001 - background broadcast must never crash the app
            logger.exception("WebSocket broadcast failed")

    # -- connections --------------------------------------------------------
    async def connect_queue(self, websocket: WebSocket, doctor_id: int, info: ClientInfo) -> None:
        self.set_loop(asyncio.get_running_loop())
        await websocket.accept()
        self.queue_clients[doctor_id][websocket] = info

    def disconnect_queue(self, websocket: WebSocket, doctor_id: int) -> None:
        clients = self.queue_clients.get(doctor_id)
        if clients is not None:
            clients.pop(websocket, None)
            if not clients:
                self.queue_clients.pop(doctor_id, None)

    async def connect_user(self, websocket: WebSocket, user_id: int) -> None:
        self.set_loop(asyncio.get_running_loop())
        await websocket.accept()
        self.user_clients[user_id].add(websocket)

    def disconnect_user(self, websocket: WebSocket, user_id: int) -> None:
        sockets = self.user_clients.get(user_id)
        if sockets is not None:
            sockets.discard(websocket)
            if not sockets:
                self.user_clients.pop(user_id, None)

    # -- sending ------------------------------------------------------------
    @staticmethod
    async def _send(websocket: WebSocket, payload: dict) -> bool:
        """Send JSON; return False if the client is gone."""
        try:
            await websocket.send_json(payload)
            return True
        except Exception:  # noqa: BLE001 - any send error means the client is disconnected
            return False

    async def send_snapshot_to(self, websocket: WebSocket, doctor_id: int, info: ClientInfo) -> None:
        """Send the current queue to one client (used right after it connects)."""
        snapshot = await anyio.to_thread.run_sync(_load_snapshot, doctor_id)
        if snapshot is not None:
            await self._send(websocket, personalize(snapshot, info))

    async def send_to_user(self, user_id: int, payload: dict) -> None:
        for websocket in list(self.user_clients.get(user_id, ())):
            if not await self._send(websocket, payload):
                self.disconnect_user(websocket, user_id)

    async def broadcast_queue(self, doctor_id: int) -> None:
        """Push the fresh queue state to everyone watching this doctor's queue."""
        if not self.queue_clients.get(doctor_id) and not self.user_clients:
            return

        snapshot = await anyio.to_thread.run_sync(_load_snapshot, doctor_id)
        if snapshot is None:
            return

        for websocket, info in list(self.queue_clients.get(doctor_id, {}).items()):
            if not await self._send(websocket, personalize(snapshot, info)):
                self.disconnect_queue(websocket, doctor_id)

        await self._notify_next_patient(snapshot)

    async def _notify_next_patient(self, snapshot: dict) -> None:
        """Tell the first waiting patient "You are next" (once per appointment)."""
        doctor_id = snapshot["doctor_id"]
        entries = snapshot["entries"]

        # forget patients who are no longer waiting for this doctor
        waiting_ids = {entry["appointment_id"] for entry in entries}
        self._notified_next[doctor_id] &= waiting_ids

        if not entries:
            return
        first = entries[0]
        if first["appointment_id"] in self._notified_next[doctor_id]:
            return
        self._notified_next[doctor_id].add(first["appointment_id"])
        await self.send_to_user(
            first["patient_user_id"],
            {
                "type": "notification",
                "event": "you_are_next",
                "message": "You are next, please be ready",
                "doctor_id": doctor_id,
                "appointment_number": first["appointment_number"],
                "token_number": first["token_number"],
            },
        )


manager = ConnectionManager()
