from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.config import BASE_DIR

router = APIRouter(tags=["Pages"])


@router.get("/queue-test", include_in_schema=True, summary="WebSocket queue test page")
def queue_test_page():
    """Simple HTML page for testing the live queue WebSocket in a browser."""
    return FileResponse(BASE_DIR / "static" / "queue_test.html", media_type="text/html")


@router.get("/health", summary="Health check")
def health():
    return {"status": "ok"}
