from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, pagination_params, require_admin
from app.models.user import User
from app.schemas.common import MessageOut, Page, Pagination
from app.schemas.department import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.services import department_service

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(
    data: DepartmentCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return department_service.create_department(db, data)


@router.get("", response_model=Page[DepartmentOut])
def list_departments(
    _user: User = Depends(get_current_user),
    pagination: Pagination = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    items, total = department_service.list_departments(db, pagination)
    return Page[DepartmentOut](
        items=[DepartmentOut.model_validate(i) for i in items],
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.put("/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: int,
    data: DepartmentUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return department_service.update_department(db, department_id, data)


@router.delete("/{department_id}", response_model=MessageOut)
def delete_department(
    department_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    department_service.delete_department(db, department_id)
    return MessageOut(message="Department deleted")
