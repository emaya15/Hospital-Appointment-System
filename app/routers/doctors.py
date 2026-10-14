from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, pagination_params, require_admin
from app.models.enums import Role
from app.models.user import User
from app.schemas.common import MessageOut, Page, Pagination
from app.schemas.doctor import DoctorCreate, DoctorOut, DoctorUpdate
from app.services import doctor_service

router = APIRouter(prefix="/doctors", tags=["Doctors"])


@router.post("", response_model=DoctorOut, status_code=status.HTTP_201_CREATED)
def create_doctor(data: DoctorCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Create a doctor profile for a user that has the DOCTOR role (admin only)."""
    return doctor_service.create_doctor(db, data)


@router.get("", response_model=Page[DoctorOut])
def list_doctors(
    department_id: int | None = Query(None, description="Filter by department"),
    specialization: str | None = Query(None, description="Partial, case-insensitive match"),
    name: str | None = Query(None, description="Partial doctor name"),
    include_inactive: bool = Query(False, description="Admins only: also list inactive doctors"),
    user: User = Depends(get_current_user),
    pagination: Pagination = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    """Patients and doctors see active doctors only. Admins can include inactive ones."""
    items, total = doctor_service.list_doctors(
        db,
        pagination,
        department_id=department_id,
        specialization=specialization,
        name=name,
        include_inactive=include_inactive and user.role == Role.ADMIN,
    )
    return Page[DoctorOut](
        items=[DoctorOut.model_validate(i) for i in items],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get("/{doctor_id}", response_model=DoctorOut)
def get_doctor(doctor_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return doctor_service.get_doctor_or_404(db, doctor_id, only_active=user.role != Role.ADMIN)


@router.put("/{doctor_id}", response_model=DoctorOut)
def update_doctor(
    doctor_id: int, data: DoctorUpdate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return doctor_service.update_doctor(db, doctor_id, data)


@router.delete("/{doctor_id}", response_model=MessageOut)
def delete_doctor(doctor_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Soft delete: the doctor is deactivated, not removed."""
    doctor_service.delete_doctor(db, doctor_id)
    return MessageOut(message="Doctor deactivated")
