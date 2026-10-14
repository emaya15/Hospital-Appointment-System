"""Registration, login, token refresh and logout."""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import security
from app.config import settings
from app.models.doctor import Doctor
from app.models.enums import Role
from app.models.patient import Patient
from app.models.token import RefreshToken
from app.models.user import User
from app.schemas.auth import AdminCreateUserRequest, RegisterRequest, TokenResponse
from app.utils import clock
from app.utils.db import commit_or_conflict
from app.utils.exceptions import BadRequestError, ConflictError, ForbiddenError, UnauthorizedError

logger = logging.getLogger(__name__)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def register_patient(db: Session, data: RegisterRequest) -> User:
    """Public registration. Always creates a PATIENT (never a doctor or admin)."""
    if get_user_by_email(db, data.email):
        raise ConflictError("Email is already registered")

    user = User(
        email=data.email.lower(),
        hashed_password=security.hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        role=Role.PATIENT,
    )
    db.add(user)
    db.flush()
    db.add(
        Patient(
            user_id=user.id,
            date_of_birth=data.date_of_birth,
            gender=data.gender,
            address=data.address,
        )
    )
    commit_or_conflict(db, "Email is already registered")
    return user


def create_user_by_admin(db: Session, data: AdminCreateUserRequest) -> User:
    """Admin-only creation of ADMIN or DOCTOR accounts."""
    if get_user_by_email(db, data.email):
        raise ConflictError("Email is already registered")

    user = User(
        email=data.email.lower(),
        hashed_password=security.hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        role=Role(data.role),
    )
    db.add(user)
    commit_or_conflict(db, "Email is already registered")
    return user


def _issue_tokens(db: Session, user: User) -> TokenResponse:
    access = security.create_access_token(user)
    refresh, expires_at = security.create_refresh_token(user)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=security.hash_token(refresh),
            expires_at=expires_at,
        )
    )
    db.commit()
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def login(db: Session, email: str, password: str) -> TokenResponse:
    user = get_user_by_email(db, email)
    # Same message for "unknown email" and "wrong password" (no user enumeration).
    if user is None or not security.verify_password(password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password")
    if not user.is_active:
        raise ForbiddenError("This account is inactive")
    return _issue_tokens(db, user)


def refresh_tokens(db: Session, refresh_token: str) -> TokenResponse:
    """Exchange a valid refresh token for a new pair (the old refresh token is revoked)."""
    security.decode_token(refresh_token, security.REFRESH)

    record = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == security.hash_token(refresh_token))
    )
    if record is None or record.revoked or record.expires_at <= clock.utcnow():
        raise UnauthorizedError("Refresh token is invalid or has been revoked")

    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive")

    record.revoked = True
    return _issue_tokens(db, user)


def logout(db: Session, user: User, refresh_token: str) -> None:
    """Revoke the given refresh token (it must belong to the logged-in user)."""
    record = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == security.hash_token(refresh_token))
    )
    if record is None:
        raise BadRequestError("Invalid refresh token")
    if record.user_id != user.id:
        raise ForbiddenError("This refresh token does not belong to you")
    if not record.revoked:
        record.revoked = True
        db.commit()


def purge_expired_tokens(db: Session) -> int:
    """Housekeeping helper: delete refresh tokens that expired more than a day ago."""
    cutoff = clock.utcnow() - timedelta(days=1)
    expired = db.scalars(select(RefreshToken).where(RefreshToken.expires_at < cutoff)).all()
    for record in expired:
        db.delete(record)
    db.commit()
    return len(expired)


def seed_default_admin(db: Session) -> bool:
    """Create the default ADMIN account from FIRST_ADMIN_* settings if it does not exist.

    Runs every time the server starts. It is safe to run repeatedly: an existing account
    is never changed or duplicated. Returns True only when a new admin was created.
    """
    email = settings.FIRST_ADMIN_EMAIL
    password = settings.FIRST_ADMIN_PASSWORD
    phone = settings.FIRST_ADMIN_PHONE

    if not email or not password:
        logger.warning("Default admin not created: set FIRST_ADMIN_EMAIL and FIRST_ADMIN_PASSWORD in .env")
        return False
    if len(password) < 8 or not (phone.isdigit() and len(phone) == 10):
        logger.warning("Default admin not created: password needs 8+ characters and phone exactly 10 digits")
        return False
    if get_user_by_email(db, email) is not None:
        logger.info("Default admin already exists")
        return False

    db.add(
        User(
            email=email,
            hashed_password=security.hash_password(password),
            full_name=settings.FIRST_ADMIN_NAME or "System Admin",
            phone=phone,
            role=Role.ADMIN,
        )
    )
    commit_or_conflict(db, "Default admin already exists")
    logger.info("Default admin account created: %s", email)
    return True


def get_profile_ids(db: Session, user: User) -> tuple[int | None, int | None]:
    """Return (patient_id, doctor_id) for the user (either may be None)."""
    patient_id = db.scalar(select(Patient.id).where(Patient.user_id == user.id))
    doctor_id = db.scalar(select(Doctor.id).where(Doctor.user_id == user.id))
    return patient_id, doctor_id
