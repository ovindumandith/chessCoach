from fastapi import APIRouter

from chesscoach import cohort
from chesscoach.api.deps import CurrentUser, DbSession

router = APIRouter(prefix="/cohort", tags=["cohort"])


@router.get("/mistakes")
def cohort_mistakes(db: DbSession, user: CurrentUser) -> dict:
    """The mistakes the coach's students make, grouped by skill across all of them."""
    return cohort.mistake_overview(db, user)
