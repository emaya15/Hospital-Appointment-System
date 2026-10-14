"""All API routers. ``main.py`` includes every router listed here."""

from app.routers import (
    appointments,
    auth,
    consultations,
    departments,
    doctors,
    files,
    pages,
    patients,
    queue,
    ratings,
    reports,
    schedules,
)

# NOTE: "queue" is listed before "doctors" so PUT /doctors/me/call-next is matched first.
all_routers = [
    pages.router,
    auth.router,
    departments.router,
    queue.router,
    doctors.router,
    schedules.router,
    appointments.router,
    consultations.router,
    files.router,
    patients.router,
    ratings.router,
    reports.router,
]
