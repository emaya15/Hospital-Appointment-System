"""FastAPI application entry point.

Run with:  uvicorn app.main:app --reload
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import SessionLocal
from app.jobs.scheduler import start_scheduler
from app.routers import all_routers
from app.services import auth_service
from app.utils.exceptions import AppError
from app.websockets.manager import manager
from app.websockets.routes import router as websocket_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("app")


def create_default_admin() -> None:
    """On startup, create the default admin account if it does not exist yet."""
    try:
        with SessionLocal() as db:
            auth_service.seed_default_admin(db)
    except Exception as exc:  # noqa: BLE001 - never stop the server because of seeding
        logger.error(
            "Could not create the default admin (%s). Did you run 'alembic upgrade head'?", type(exc).__name__
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the scheduler when the app starts and stop it when the app shuts down."""
    manager.set_loop(asyncio.get_running_loop())
    create_default_admin()
    scheduler = start_scheduler()
    if settings.MAIL_MODE != "smtp":
        logger.info("MAIL_MODE=%s: e-mails are only logged, not sent", settings.MAIL_MODE)
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Hospital appointment booking with live queue, e-mail notifications and reports.",
    lifespan=lifespan,
)

for router in all_routers:
    app.include_router(router)
app.include_router(websocket_router)


# --------------------------------------------------------------------------- error handling
@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail}, headers=getattr(exc, "headers", None)
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    """422 with a clean list of problems (no request body echoed back)."""
    errors = [
        {"field": ".".join(str(part) for part in err["loc"] if part != "body"), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": "Validation error", "errors": errors})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    """Last resort: log the details on the server, return a generic message to the client."""
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, type(exc).__name__, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
