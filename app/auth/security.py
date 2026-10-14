"""Password hashing and JWT helpers (reusable by HTTP routes and WebSockets)."""

import hashlib
import uuid
from datetime import datetime, timedelta

import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.utils import clock
from app.utils.exceptions import UnauthorizedError

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS = "access"
REFRESH = "refresh"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError:
        return False


def hash_token(token: str) -> str:
    """SHA-256 of a token. Only the hash of a refresh token is stored in the DB."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user: User) -> str:
    expires = clock.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user.id), "role": user.role.value, "type": ACCESS, "exp": expires}
    return jwt.encode(payload, settings.require_jwt_secret(), algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user: User) -> tuple[str, datetime]:
    """Return (token, expiry). The token carries a random id so every token is unique."""
    expires = clock.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user.id), "type": REFRESH, "jti": uuid.uuid4().hex, "exp": expires}
    token = jwt.encode(payload, settings.require_jwt_secret(), algorithm=settings.JWT_ALGORITHM)
    return token, expires


def decode_token(token: str, expected_type: str) -> dict:
    """Validate signature, expiry and token type. Raises UnauthorizedError (401)."""
    try:
        payload = jwt.decode(token, settings.require_jwt_secret(), algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid token") from exc

    if payload.get("type") != expected_type or "sub" not in payload:
        raise UnauthorizedError("Invalid token")
    return payload


def user_from_access_token(db: Session, token: str) -> User:
    """Load the active user that owns an access token (used by HTTP and WebSocket auth)."""
    payload = decode_token(token, ACCESS)
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise UnauthorizedError("Invalid token") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive")
    return user
