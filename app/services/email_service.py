"""Sending e-mail through SMTP (``smtplib``) or in mock mode.

* ``MAIL_MODE=mock`` (default) never touches the network. The e-mail is only logged
  (recipient is masked, the body is never logged) and kept in ``sent_mock_emails``.
* ``MAIL_MODE=smtp`` sends through the SMTP server configured in ``.env``.

A failed e-mail is logged and returns False. It NEVER raises, so a completed booking,
cancellation or consultation is never undone because of an e-mail problem.
Passwords and tokens are never logged.
"""

import logging
import smtplib
from collections import deque
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage

from fastapi import BackgroundTasks

from app.config import settings

logger = logging.getLogger(__name__)

# Inspect this in tests / local development when MAIL_MODE=mock
sent_mock_emails: deque = deque(maxlen=200)


@dataclass
class EmailMessage:
    to: str
    subject: str
    body: str


def _mask(address: str) -> str:
    name, _, domain = address.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


def _smtp_is_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def send_email(message: EmailMessage) -> bool:
    """Send one e-mail. Returns True on success, False on any failure."""
    if settings.MAIL_MODE != "smtp":
        sent_mock_emails.append(message)
        logger.info("[MOCK EMAIL] to=%s subject=%r", _mask(message.to), message.subject)
        return True

    if not _smtp_is_configured():
        logger.warning(
            "E-mail NOT sent (subject=%r): MAIL_MODE=smtp but SMTP_HOST / SMTP_FROM are not set. "
            "Set them in .env or use MAIL_MODE=mock.",
            message.subject,
        )
        return False

    mime = MimeMessage()
    mime["From"] = settings.SMTP_FROM
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime.set_content(message.body)

    try:
        # Port 465 uses SSL from the first byte; other ports (587) start plain and upgrade with STARTTLS.
        if settings.SMTP_PORT == 465:
            server_context = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
        else:
            server_context = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
        with server_context as server:
            if settings.SMTP_USE_TLS and settings.SMTP_PORT != 465:
                server.starttls()
            if settings.SMTP_USERNAME:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(mime)
    except Exception as exc:  # noqa: BLE001 - e-mail problems must never break the request
        logger.error(
            "E-mail NOT sent (subject=%r, to=%s): SMTP unavailable or rejected "
            "(%s: %s) [host=%s port=%s user_set=%s password_length=%d]",
            message.subject,
            _mask(message.to),
            type(exc).__name__,
            str(exc)[:120],
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            bool(settings.SMTP_USERNAME),
            len(settings.SMTP_PASSWORD or ""),
        )
        return False

    logger.info("E-mail sent (subject=%r, to=%s)", message.subject, _mask(message.to))
    return True


def dispatch(background_tasks: BackgroundTasks | None, message: EmailMessage) -> None:
    """Queue the e-mail as a FastAPI background task (runs after the response is sent).

    Without a BackgroundTasks object (e.g. inside a scheduled job) it is sent directly.
    """
    if background_tasks is not None:
        background_tasks.add_task(send_email, message)
    else:
        send_email(message)