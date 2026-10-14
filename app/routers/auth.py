from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_admin
from app.models.user import User
from app.schemas.auth import (
    AdminCreateUserRequest,
    LoginRequest,
    LogoutRequest,
    MeOut,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.schemas.common import MessageOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """Public registration. Always creates a PATIENT account."""
    return auth_service.register_patient(db, data)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    return auth_service.login(db, data.email, data.password)


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    """Get a new access + refresh token. The old refresh token stops working."""
    return auth_service.refresh_tokens(db, data.refresh_token)


@router.post("/logout", response_model=MessageOut)
def logout(data: LogoutRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Revoke the refresh token."""
    auth_service.logout(db, user, data.refresh_token)
    return MessageOut(message="Logged out successfully")


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patient_id, doctor_id = auth_service.get_profile_ids(db, user)
    out = MeOut.model_validate(user)
    out.patient_id = patient_id
    out.doctor_id = doctor_id
    return out


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an ADMIN or DOCTOR account (admin only)",
)
def create_user(
    data: AdminCreateUserRequest,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return auth_service.create_user_by_admin(db, data)
