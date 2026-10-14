"""Small, thread-safe helpers that services call to push real-time updates.

Call these AFTER ``db.commit()`` so the WebSocket layer reads the final data.
If nobody is connected (or the server loop is not running) they do nothing.
"""

from app.websockets.manager import manager


def queue_changed(doctor_id: int) -> None:
    """Re-broadcast a doctor's queue to all connected clients."""
    manager.schedule(manager.broadcast_queue(doctor_id))


def notify_user(user_id: int, event: str, message: str, data: dict | None = None) -> None:
    """Send a personal notification to every open connection of one user."""
    payload = {"type": "notification", "event": event, "message": message}
    if data:
        payload["data"] = data
    manager.schedule(manager.send_to_user(user_id, payload))
