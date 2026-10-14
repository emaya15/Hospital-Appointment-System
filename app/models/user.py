from sqlalchemy import Boolean, Enum, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import Role
from app.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    """Login account. Role decides what the user may do."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(150))
    phone: Mapped[str] = mapped_column(String(10))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
