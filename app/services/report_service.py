"""Admin reports and dashboard (all numbers come from SQLAlchemy queries)."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, case, extract, func, select
from sqlalchemy.orm import Session

from app.models.appointment import Appointment
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.enums import AppointmentStatus
from app.models.patient import Patient
from app.models.user import User
from app.schemas.common import Pagination
from app.schemas.report import (
    DashboardOut,
    DepartmentSummaryOut,
    DepartmentSummaryRow,
    DoctorPerformanceOut,
    DoctorPerformanceRow,
    FrequentNoShowRow,
    FrequentNoShowsOut,
    HourCount,
    PeakHoursOut,
)
from app.utils import clock
from app.utils.exceptions import BadRequestError
from app.utils.pagination import paginate_rows

S = AppointmentStatus
MAX_RANGE_DAYS = 366


def resolve_range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Validate a date range. Default: the last 30 days up to today."""
    end = date_to or clock.today()
    start = date_from or (end - timedelta(days=29))
    if start > end:
        raise BadRequestError("date_from must not be later than date_to")
    if (end - start).days > MAX_RANGE_DAYS:
        raise BadRequestError(f"The date range cannot be longer than {MAX_RANGE_DAYS} days")
    return start, end


def _count_if(condition):
    """SUM(CASE WHEN condition THEN 1 ELSE 0 END) as an integer expression."""
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def dashboard(db: Session) -> DashboardOut:
    today = clock.today()
    rows = db.execute(
        select(Appointment.status, func.count(Appointment.id))
        .where(Appointment.appointment_date == today)
        .group_by(Appointment.status)
    ).all()
    counts = {status: int(count) for status, count in rows}

    revenue = db.scalar(
        select(func.coalesce(func.sum(Appointment.consultation_fee), 0)).where(
            Appointment.appointment_date == today, Appointment.status == S.COMPLETED
        )
    )
    return DashboardOut(
        date=today,
        total_appointments=sum(counts.values()),
        booked=counts.get(S.BOOKED, 0),
        checked_in=counts.get(S.CHECKED_IN, 0),
        in_consultation=counts.get(S.IN_CONSULTATION, 0),
        completed=counts.get(S.COMPLETED, 0),
        cancelled=counts.get(S.CANCELLED, 0),
        no_show=counts.get(S.NO_SHOW, 0),
        revenue=Decimal(str(revenue or 0)),
    )


def doctor_performance(
    db: Session, date_from: date | None, date_to: date | None, pagination: Pagination
) -> DoctorPerformanceOut:
    start, end = resolve_range(date_from, date_to)

    stmt = (
        select(
            Doctor.id.label("doctor_id"),
            User.full_name.label("doctor_name"),
            Department.name.label("department_name"),
            func.count(Appointment.id).label("total"),
            _count_if(Appointment.status == S.COMPLETED).label("completed"),
            _count_if(Appointment.status == S.CANCELLED).label("cancelled"),
            _count_if(Appointment.status == S.NO_SHOW).label("no_shows"),
            func.coalesce(
                func.sum(case((Appointment.status == S.COMPLETED, Appointment.consultation_fee), else_=0)), 0
            ).label("revenue"),
        )
        .select_from(Doctor)
        .join(User, User.id == Doctor.user_id)
        .join(Department, Department.id == Doctor.department_id)
        .outerjoin(
            Appointment,
            and_(
                Appointment.doctor_id == Doctor.id,
                Appointment.appointment_date >= start,
                Appointment.appointment_date <= end,
            ),
        )
        .group_by(Doctor.id, User.full_name, Department.name)
        .order_by(User.full_name, Doctor.id)
    )
    rows, total = paginate_rows(db, stmt, pagination)

    items = []
    for row in rows:
        expected = int(row.total) - int(row.cancelled)  # appointments that were really expected
        percentage = round(int(row.no_shows) / expected * 100, 2) if expected > 0 else 0.0
        items.append(
            DoctorPerformanceRow(
                doctor_id=row.doctor_id,
                doctor_name=row.doctor_name,
                department_name=row.department_name,
                total_appointments=int(row.total),
                completed_consultations=int(row.completed),
                cancelled=int(row.cancelled),
                no_shows=int(row.no_shows),
                no_show_percentage=percentage,
                revenue=Decimal(str(row.revenue or 0)),
            )
        )
    return DoctorPerformanceOut(
        date_from=start, date_to=end, total=total, skip=pagination.skip, limit=pagination.limit, items=items
    )


def department_summary(
    db: Session, date_from: date | None, date_to: date | None, pagination: Pagination
) -> DepartmentSummaryOut:
    start, end = resolve_range(date_from, date_to)

    stmt = (
        select(
            Department.id.label("department_id"),
            Department.name.label("department_name"),
            func.count(Appointment.id).label("total"),
            _count_if(Appointment.status == S.COMPLETED).label("completed"),
            _count_if(Appointment.status == S.CANCELLED).label("cancelled"),
            _count_if(Appointment.status == S.NO_SHOW).label("no_shows"),
        )
        .select_from(Department)
        .outerjoin(Doctor, Doctor.department_id == Department.id)
        .outerjoin(
            Appointment,
            and_(
                Appointment.doctor_id == Doctor.id,
                Appointment.appointment_date >= start,
                Appointment.appointment_date <= end,
            ),
        )
        .where(Department.is_active.is_(True))
        .group_by(Department.id, Department.name)
        .order_by(Department.name)
    )
    rows, total = paginate_rows(db, stmt, pagination)
    items = [
        DepartmentSummaryRow(
            department_id=row.department_id,
            department_name=row.department_name,
            total_appointments=int(row.total),
            completed=int(row.completed),
            cancelled=int(row.cancelled),
            no_shows=int(row.no_shows),
        )
        for row in rows
    ]
    return DepartmentSummaryOut(
        date_from=start, date_to=end, total=total, skip=pagination.skip, limit=pagination.limit, items=items
    )


def peak_hours(db: Session, date_from: date | None, date_to: date | None) -> PeakHoursOut:
    """Number of (non-cancelled) appointments for each hour of the day."""
    start, end = resolve_range(date_from, date_to)
    hour = extract("hour", Appointment.appointment_time)

    rows = db.execute(
        select(hour.label("hour"), func.count(Appointment.id).label("total"))
        .where(
            Appointment.appointment_date >= start,
            Appointment.appointment_date <= end,
            Appointment.status != S.CANCELLED,
        )
        .group_by(hour)
        .order_by(hour)
    ).all()

    hours = [HourCount(hour=int(r.hour), appointments=int(r.total)) for r in rows]
    busiest = max(hours, key=lambda h: (h.appointments, -h.hour)).hour if hours else None
    return PeakHoursOut(date_from=start, date_to=end, busiest_hour=busiest, hours=hours)


def frequent_no_shows(db: Session, pagination: Pagination, *, min_count: int = 3) -> FrequentNoShowsOut:
    """Patients with at least ``min_count`` no-shows in the previous 90 days."""
    until = clock.today()
    since = until - timedelta(days=90)

    count = func.count(Appointment.id)
    stmt = (
        select(
            Patient.id.label("patient_id"),
            User.full_name.label("patient_name"),
            User.email.label("email"),
            count.label("no_shows"),
        )
        .select_from(Appointment)
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(User, User.id == Patient.user_id)
        .where(
            Appointment.status == S.NO_SHOW,
            Appointment.appointment_date >= since,
            Appointment.appointment_date <= until,
        )
        .group_by(Patient.id, User.full_name, User.email)
        .having(count >= min_count)
        .order_by(count.desc(), Patient.id)
    )
    rows, total = paginate_rows(db, stmt, pagination)
    items = [
        FrequentNoShowRow(
            patient_id=r.patient_id, patient_name=r.patient_name, email=r.email, no_show_count=int(r.no_shows)
        )
        for r in rows
    ]
    return FrequentNoShowsOut(
        since=since, until=until, total=total, skip=pagination.skip, limit=pagination.limit, items=items
    )
