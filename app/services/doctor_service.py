"""Doctor management and shared doctor helpers."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.enums import OPEN_STATUSES, Role
from app.models.user import User
from app.schemas.common import Pagination
from app.schemas.doctor import DoctorCreate, DoctorUpdate
from app.utils import clock
from app.utils.db import commit_or_conflict
from app.utils.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.utils.pagination import paginate


def get_doctor_or_404(db: Session, doctor_id: int, *, only_active: bool = False) -> Doctor:
    doctor = db.get(Doctor, doctor_id)
    if doctor is None or (only_active and not doctor.is_active):
        raise NotFoundError("Doctor not found")
    return doctor


def get_doctor_for_user(db: Session, user: User) -> Doctor:
    """The doctor profile of a logged-in DOCTOR user."""
    doctor = db.scalar(select(Doctor).where(Doctor.user_id == user.id))
    if doctor is None:
        raise NotFoundError("Doctor profile not found for this account")
    return doctor


def ensure_can_manage(user: User, doctor: Doctor) -> None:
    """Admins can manage any doctor; a doctor can manage only their own data."""
    if user.role == Role.ADMIN:
        return
    if user.role == Role.DOCTOR and doctor.user_id == user.id:
        return
    raise ForbiddenError("You can manage only your own schedule and leaves")


def has_upcoming_appointments(db: Session, doctor_id: int) -> bool:
    """True if the doctor still has open appointments today or later."""
    count = db.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.status.in_(OPEN_STATUSES),
            Appointment.appointment_date >= clock.today(),
        )
    )
    return bool(count)


def _validate_department(db: Session, department_id: int) -> None:
    department = db.get(Department, department_id)
    if department is None or not department.is_active:
        raise NotFoundError("Department not found")


def create_doctor(db: Session, data: DoctorCreate) -> Doctor:
    user = db.get(User, data.user_id)
    if user is None:
        raise NotFoundError("User not found")
    if user.role != Role.DOCTOR:
        raise BadRequestError("The user must have the DOCTOR role (create it with POST /auth/users)")
    if db.scalar(select(Doctor.id).where(Doctor.user_id == user.id)) is not None:
        raise ConflictError("This user already has a doctor profile")
    _validate_department(db, data.department_id)

    doctor = Doctor(
        user_id=user.id,
        department_id=data.department_id,
        specialization=data.specialization,
        qualification=data.qualification,
        experience_years=data.experience_years,
        consultation_fee=data.consultation_fee,
        slot_duration_minutes=data.slot_duration_minutes,
    )
    db.add(doctor)
    commit_or_conflict(db, "This user already has a doctor profile")
    return doctor


def list_doctors(
    db: Session,
    pagination: Pagination,
    *,
    department_id: int | None = None,
    specialization: str | None = None,
    name: str | None = None,
    include_inactive: bool = False,
):
    """Search doctors. Patient-facing callers only ever see active doctors."""
    stmt = select(Doctor).join(User, User.id == Doctor.user_id)
    if not include_inactive:
        stmt = stmt.where(Doctor.is_active.is_(True))
    if department_id is not None:
        stmt = stmt.where(Doctor.department_id == department_id)
    if specialization:
        stmt = stmt.where(Doctor.specialization.ilike(f"%{specialization.strip()}%"))
    if name:
        stmt = stmt.where(User.full_name.ilike(f"%{name.strip()}%"))
    stmt = stmt.order_by(User.full_name, Doctor.id)
    return paginate(db, stmt, pagination)


def _set_active(doctor: Doctor, active: bool) -> None:
    """Doctor and login account are activated/deactivated together."""
    doctor.is_active = active
    doctor.user.is_active = active


def update_doctor(db: Session, doctor_id: int, data: DoctorUpdate) -> Doctor:
    doctor = get_doctor_or_404(db, doctor_id)
    changes = data.model_dump(exclude_unset=True)

    if "department_id" in changes and changes["department_id"] is not None:
        _validate_department(db, changes["department_id"])
        doctor.department_id = changes["department_id"]

    for field in (
        "specialization",
        "qualification",
        "experience_years",
        "consultation_fee",
        "slot_duration_minutes",
    ):
        if field in changes and changes[field] is not None:
            setattr(doctor, field, changes[field])

    if "is_active" in changes and changes["is_active"] is not None:
        if changes["is_active"] is False and doctor.is_active and has_upcoming_appointments(db, doctor.id):
            raise BadRequestError("Cannot deactivate a doctor who has upcoming appointments")
        _set_active(doctor, changes["is_active"])

    db.commit()
    return doctor


def delete_doctor(db: Session, doctor_id: int) -> None:
    """Soft delete: the row is kept (appointments still reference it)."""
    doctor = get_doctor_or_404(db, doctor_id)
    if has_upcoming_appointments(db, doctor.id):
        raise BadRequestError("Cannot deactivate a doctor who has upcoming appointments")
    _set_active(doctor, False)
    db.commit()
