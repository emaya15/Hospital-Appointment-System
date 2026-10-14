from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.appointment import Appointment
from app.models.enums import FileCategory
from app.models.mixins import TimestampMixin


class UploadedFile(TimestampMixin, Base):
    """Metadata of a file stored on disk. The disk name is a random UUID."""

    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), index=True)
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category: Mapped[FileCategory] = mapped_column(Enum(FileCategory, native_enum=False, length=20))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(100), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column()

    appointment: Mapped[Appointment] = relationship(back_populates="files")
