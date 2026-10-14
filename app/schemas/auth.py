from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.models.enums import Role
from app.schemas.common import PhoneStr

Password = Annotated[str, StringConstraints(min_length=8, max_length=64)]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=150)]


def _check_password_strength(value: str) -> str:
    if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
        raise ValueError("Password must contain at least one letter and one digit")
    return value


class RegisterRequest(BaseModel):
    """Public registration. It always creates a PATIENT account."""

    email: EmailStr
    password: Password
    full_name: FullName
    phone: PhoneStr
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def lower_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        return _check_password_strength(value)

    @field_validator("date_of_birth")
    @classmethod
    def dob_not_in_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("date_of_birth cannot be in the future")
        return value


class AdminCreateUserRequest(BaseModel):
    """Admin-only: create an ADMIN or DOCTOR account."""

    email: EmailStr
    password: Password
    full_name: FullName
    phone: PhoneStr
    role: Literal["ADMIN", "DOCTOR"]

    @field_validator("email")
    @classmethod
    def lower_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        return _check_password_strength(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def lower_email(cls, value: str) -> str:
        return value.lower()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    phone: str
    role: Role
    is_active: bool
    created_at: datetime


class MeOut(UserOut):
    patient_id: int | None = None
    doctor_id: int | None = None
