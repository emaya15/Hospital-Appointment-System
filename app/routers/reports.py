from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, pagination_params, require_admin
from app.models.user import User
from app.schemas.common import Pagination
from app.schemas.report import (
    DashboardOut,
    DepartmentSummaryOut,
    DoctorPerformanceOut,
    FrequentNoShowsOut,
    PeakHoursOut,
)
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Admin Reports"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Today's totals, status counts and consultation revenue."""
    return report_service.dashboard(db)


@router.get("/doctor-performance", response_model=DoctorPerformanceOut)
def doctor_performance(
    date_from: date | None = Query(None, description="YYYY-MM-DD (default: 29 days before date_to)"),
    date_to: date | None = Query(None, description="YYYY-MM-DD (default: today)"),
    _admin: User = Depends(require_admin),
    pagination: Pagination = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    return report_service.doctor_performance(db, date_from, date_to, pagination)


@router.get("/department-summary", response_model=DepartmentSummaryOut)
def department_summary(
    date_from: date | None = Query(None, description="YYYY-MM-DD"),
    date_to: date | None = Query(None, description="YYYY-MM-DD"),
    _admin: User = Depends(require_admin),
    pagination: Pagination = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    return report_service.department_summary(db, date_from, date_to, pagination)


@router.get("/peak-hours", response_model=PeakHoursOut)
def peak_hours(
    date_from: date | None = Query(None, description="YYYY-MM-DD"),
    date_to: date | None = Query(None, description="YYYY-MM-DD"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return report_service.peak_hours(db, date_from, date_to)


@router.get("/frequent-no-shows", response_model=FrequentNoShowsOut)
def frequent_no_shows(
    _admin: User = Depends(require_admin),
    pagination: Pagination = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    """Patients with at least three no-shows in the previous 90 days."""
    return report_service.frequent_no_shows(db, pagination)
