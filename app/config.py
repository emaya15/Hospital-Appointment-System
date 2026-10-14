"""Application settings.

All configuration comes from environment variables (loaded from the ".env" file
in the project root). Nothing secret is hard-coded in the source code.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be a whole number") from exc


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default_folder: str) -> Path:
    path = Path(_env(name, default_folder))
    return path if path.is_absolute() else BASE_DIR / path


@dataclass
class Settings:
    APP_NAME: str = field(default_factory=lambda: _env("APP_NAME", "Hospital Appointment System"))
    HOSPITAL_NAME: str = field(default_factory=lambda: _env("HOSPITAL_NAME", "City General Hospital"))
    TIMEZONE: str = field(default_factory=lambda: _env("TIMEZONE", "Asia/Kolkata"))

    DATABASE_URL: str = field(default_factory=lambda: _env("DATABASE_URL"))

    JWT_SECRET_KEY: str = field(default_factory=lambda: _env("JWT_SECRET_KEY"))
    JWT_ALGORITHM: str = field(default_factory=lambda: _env("JWT_ALGORITHM", "HS256"))
    ACCESS_TOKEN_EXPIRE_MINUTES: int = field(default_factory=lambda: _env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
    REFRESH_TOKEN_EXPIRE_DAYS: int = field(default_factory=lambda: _env_int("REFRESH_TOKEN_EXPIRE_DAYS", 7))

    MAIL_MODE: str = field(default_factory=lambda: _env("MAIL_MODE", "mock").lower())
    SMTP_HOST: str = field(default_factory=lambda: _env("SMTP_HOST"))
    SMTP_PORT: int = field(default_factory=lambda: _env_int("SMTP_PORT", 587))
    SMTP_USERNAME: str = field(default_factory=lambda: _env("SMTP_USERNAME"))
    SMTP_PASSWORD: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    SMTP_FROM: str = field(default_factory=lambda: _env("SMTP_FROM"))
    SMTP_USE_TLS: bool = field(default_factory=lambda: _env_bool("SMTP_USE_TLS", True))

    SCHEDULER_ENABLED: bool = field(default_factory=lambda: _env_bool("SCHEDULER_ENABLED", True))
    NO_SHOW_GRACE_MINUTES: int = field(default_factory=lambda: _env_int("NO_SHOW_GRACE_MINUTES", 15))

    UPLOAD_DIR: Path = field(default_factory=lambda: _env_path("UPLOAD_DIR", "uploads"))
    PDF_DIR: Path = field(default_factory=lambda: _env_path("PDF_DIR", "generated_pdfs"))
    MAX_UPLOAD_MB: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_MB", 5))

    # Default admin created automatically when the server starts (if it does not exist yet)
    FIRST_ADMIN_EMAIL: str = field(default_factory=lambda: _env("FIRST_ADMIN_EMAIL").lower())
    FIRST_ADMIN_PASSWORD: str = field(default_factory=lambda: os.getenv("FIRST_ADMIN_PASSWORD", ""))
    FIRST_ADMIN_NAME: str = field(default_factory=lambda: _env("FIRST_ADMIN_NAME", "System Admin"))
    FIRST_ADMIN_PHONE: str = field(default_factory=lambda: _env("FIRST_ADMIN_PHONE", "9999999999"))

    # Business rules
    MAX_BOOKING_DAYS_AHEAD: int = 30
    MIN_HOURS_BEFORE_CHANGE: int = 2
    MAX_RESCHEDULES: int = 2
    CHECK_IN_OPENS_MINUTES_BEFORE: int = 30

    @property
    def MAX_UPLOAD_BYTES(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    def require_jwt_secret(self) -> str:
        if not self.JWT_SECRET_KEY:
            raise RuntimeError("JWT_SECRET_KEY is not set. Copy .env.example to .env and set it.")
        return self.JWT_SECRET_KEY


settings = Settings()
