"""Create the first ADMIN account from the FIRST_ADMIN_* values in .env.

Usage (after `alembic upgrade head`):
    python -m scripts.create_admin
"""

import os
import sys

from sqlalchemy import select

from app.auth.security import hash_password
from app.database import SessionLocal
from app.models.enums import Role
from app.models.user import User


def main() -> int:
    email = os.getenv("FIRST_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("FIRST_ADMIN_PASSWORD", "")
    name = os.getenv("FIRST_ADMIN_NAME", "System Admin").strip()
    phone = os.getenv("FIRST_ADMIN_PHONE", "9999999999").strip()

    if not email or len(password) < 8:
        print("Set FIRST_ADMIN_EMAIL and FIRST_ADMIN_PASSWORD (min 8 characters) in .env first.")
        return 1
    if not (phone.isdigit() and len(phone) == 10):
        print("FIRST_ADMIN_PHONE must be exactly 10 digits.")
        return 1

    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            print(f"An account with e-mail {email} already exists. Nothing to do.")
            return 0
        db.add(
            User(
                email=email,
                hashed_password=hash_password(password),
                full_name=name,
                phone=phone,
                role=Role.ADMIN,
            )
        )
        db.commit()
    print(f"Admin account created: {email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
