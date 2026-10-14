from datetime import date

from pydantic import BaseModel

from app.schemas.common import MoneyOut


class DashboardOut(BaseModel):
    date: date
    total_appointments: int
    booked: int
    checked_in: int
    in_consultation: int
    completed: int
    cancelled: int
    no_show: int
    revenue: MoneyOut


class DoctorPerformanceRow(BaseModel):
    doctor_id: int
    doctor_name: str
    department_name: str
    total_appointments: int
    completed_consultations: int
    cancelled: int
    no_shows: int
    no_show_percentage: float
    revenue: MoneyOut


class DoctorPerformanceOut(BaseModel):
    date_from: date
    date_to: date
    total: int
    skip: int
    limit: int
    items: list[DoctorPerformanceRow]


class DepartmentSummaryRow(BaseModel):
    department_id: int
    department_name: str
    total_appointments: int
    completed: int
    cancelled: int
    no_shows: int


class DepartmentSummaryOut(BaseModel):
    date_from: date
    date_to: date
    total: int
    skip: int
    limit: int
    items: list[DepartmentSummaryRow]


class HourCount(BaseModel):
    hour: int
    appointments: int


class PeakHoursOut(BaseModel):
    date_from: date
    date_to: date
    busiest_hour: int | None
    hours: list[HourCount]


class FrequentNoShowRow(BaseModel):
    patient_id: int
    patient_name: str
    email: str
    no_show_count: int


class FrequentNoShowsOut(BaseModel):
    since: date
    until: date
    total: int
    skip: int
    limit: int
    items: list[FrequentNoShowRow]
