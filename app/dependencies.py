"""Reusable FastAPI dependencies: DB session, authentication, roles, pagination."""

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import user_from_access_token
from app.database import get_db
from app.models.enums import Role
from app.models.user import User
from app.schemas.common import Pagination
from app.utils.exceptions import ForbiddenError, UnauthorizedError

bearer_scheme = HTTPBearer(auto_error=False, description="Paste the access token from /auth/login")

__all__ = [
    "get_db",
    "get_current_user",
    "require_roles",
    "require_admin",
    "require_doctor",
    "require_patient",
    "pagination_params",
]


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """401 if the token is missing, invalid or expired, or the user is inactive."""
    if credentials is None:
        raise UnauthorizedError("Authentication required")
    return user_from_access_token(db, credentials.credentials)


def require_roles(*roles: Role):
    """Build a dependency that allows only the given roles (403 otherwise)."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError("You do not have permission to perform this action")
        return user

    return checker


require_admin = require_roles(Role.ADMIN)
require_doctor = require_roles(Role.DOCTOR)
require_patient = require_roles(Role.PATIENT)


def pagination_params(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum records to return"),
) -> Pagination:
    return Pagination(skip=skip, limit=limit)
