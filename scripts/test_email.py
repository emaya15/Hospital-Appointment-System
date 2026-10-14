"""Check your SMTP settings step by step and send one test e-mail.

Usage (PowerShell, from the project folder):
    python -m scripts.test_email you@example.com

It prints which step works or fails: connect -> secure (TLS) -> login -> send.
Your password is never printed.
"""

import smtplib
import socket
import sys

from app.config import settings


def step(name: str, action):
    """Run one step. Returns (True, result) or (False, None) after printing the real error."""
    try:
        result = action()
        print(f"  OK     {name}")
        return True, result
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic tool, show everything useful
        print(f"  FAILED {name}: {type(exc).__name__}: {exc}")
        return False, None


def main() -> int:
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print("Usage: python -m scripts.test_email you@example.com")
        return 1
    to = sys.argv[1]

    print(f"MAIL_MODE   = {settings.MAIL_MODE}")
    print(f"SMTP_HOST   = {settings.SMTP_HOST or '(not set)'}")
    print(f"SMTP_PORT   = {settings.SMTP_PORT}  ({'SSL' if settings.SMTP_PORT == 465 else 'STARTTLS'})")
    print(f"SMTP_FROM   = {settings.SMTP_FROM or '(not set)'}")
    print(f"SMTP_USER   = {settings.SMTP_USERNAME or '(not set)'}")
    print(f"PASSWORD    = {'(set, %d characters)' % len(settings.SMTP_PASSWORD) if settings.SMTP_PASSWORD else '(NOT SET)'}")
    if settings.MAIL_MODE != "smtp":
        print("\nMAIL_MODE is not 'smtp'. Set MAIL_MODE=smtp in .env.")
        return 1
    if not settings.SMTP_HOST or not settings.SMTP_FROM:
        print("\nSMTP_HOST and SMTP_FROM must be set in .env.")
        return 1

    print("\nSteps:")
    ok, _ = step(f"DNS lookup of {settings.SMTP_HOST}", lambda: socket.gethostbyname(settings.SMTP_HOST))
    if not ok:
        print("\nCannot find the server. Check your internet connection and SMTP_HOST.")
        return 1

    if settings.SMTP_PORT == 465:
        ok, server = step("connect (SSL)", lambda: smtplib.SMTP_SSL(settings.SMTP_HOST, 465, timeout=20))
    else:
        ok, server = step("connect", lambda: smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20))
        if ok and settings.SMTP_USE_TLS:
            ok, _ = step("secure the connection (STARTTLS)", server.starttls)
    if not ok:
        print("\nThe connection was blocked or closed before login. Likely causes:")
        print("  - antivirus / firewall 'e-mail or SSL scanning' (try pausing it for this test)")
        print("  - a network that blocks SMTP (try a phone hotspot)")
        print("  - try the other Gmail port: set SMTP_PORT=465 in .env")
        return 1

    if settings.SMTP_USERNAME:
        ok, _ = step("login", lambda: server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD))
        if not ok:
            print("\nLogin refused. Gmail needs a 16-character APP PASSWORD (not your normal password),")
            print("written without spaces, and 2-Step Verification must be on for the account.")
            return 1

    message = f"From: {settings.SMTP_FROM}\r\nTo: {to}\r\nSubject: Hospital system test e-mail\r\n\r\nIf you can read this, SMTP works.\r\n"
    ok, _ = step("send", lambda: server.sendmail(settings.SMTP_FROM, [to], message))
    try:
        server.quit()
    except Exception:  # noqa: BLE001
        pass
    print("\nSENT. Check the inbox (and the Spam folder)." if ok else "\nSending failed. Read the error above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())