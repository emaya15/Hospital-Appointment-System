"""Department management (admin only; enforced in the router)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.department import Department
from app.models.doctor import Doctor
from app.schemas.common import Pagination
from app.schemas.department import DepartmentCreate, DepartmentUpdate
from app.utils.db import commit_or_conflict
from app.utils.exceptions import BadRequestError, ConflictError, NotFoundError
from app.utils.pagination import paginate


def get_department(db: Session, department_id: int) -> Department:
    department = db.get(Department, department_id)
    if department is None or not department.is_active:
        raise NotFoundError("Department not found")
    return department


def _name_taken(db: Session, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Department.id).where(func.lower(Department.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Department.id != exclude_id)
    return db.scalar(stmt) is not None


def create_department(db: Session, data: DepartmentCreate) -> Department:
    if _name_taken(db, data.name):
        raise ConflictError("A department with this name already exists")
    department = Department(name=data.name, description=data.description)
    db.add(department)
    commit_or_conflict(db, "A department with this name already exists")
    return department


def list_departments(db: Session, pagination: Pagination):
    stmt = select(Department).where(Department.is_active.is_(True)).order_by(Department.name)
    return paginate(db, stmt, pagination)


def update_department(db: Session, department_id: int, data: DepartmentUpdate) -> Department:
    department = get_department(db, department_id)
    changes = data.model_dump(exclude_unset=True)

    if "name" in changes and changes["name"]:
        if _name_taken(db, changes["name"], exclude_id=department.id):
            raise ConflictError("A department with this name already exists")
        department.name = changes["name"]
    if "description" in changes:
        department.description = changes["description"]

    commit_or_conflict(db, "A department with this name already exists")
    return department


def delete_department(db: Session, department_id: int) -> None:
    """Soft delete. Not allowed while active doctors belong to the department."""
    department = get_department(db, department_id)
    active_doctors = db.scalar(
        select(func.count()).select_from(Doctor).where(
            Doctor.department_id == department.id, Doctor.is_active.is_(True)
        )
    )
    if active_doctors:
        raise BadRequestError("Department has active doctors. Move or deactivate them first.")
    department.is_active = False
    db.commit()
