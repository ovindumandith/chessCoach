from fastapi import APIRouter, Response, status
from sqlalchemy import text

from chesscoach import __version__
from chesscoach.api.deps import DbSession
from chesscoach.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: DbSession, response: Response) -> dict:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "version": __version__,
        "environment": get_settings().app_env,
        "database": db_status,
    }
