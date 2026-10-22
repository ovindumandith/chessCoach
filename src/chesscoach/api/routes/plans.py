import uuid

from fastapi import APIRouter, status

from chesscoach.api.deps import CurrentUser, DbSession, rate_limited
from chesscoach.coaching import plan as service

router = APIRouter(tags=["improvement plans"])


@router.get("/students/{student_id}/improvement-plans")
def list_plans(student_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    """Eligibility (analyzed games vs. required) and every past plan, newest first."""
    return service.plan_overview(db, user, student_id)


@router.post(
    "/students/{student_id}/improvement-plans",
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limited("lessons", lambda s: s.rate_limit_lessons_per_hour)],
)
def create_plan(student_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    """Send all analyzed games to the LLM and store the checked plan (the student only)."""
    return service.plan_out(db, service.create_plan(db, user, student_id))


@router.get("/improvement-plans/{plan_id}")
def get_plan(
    plan_id: uuid.UUID, db: DbSession, user: CurrentUser, include_context: bool = False
) -> dict:
    """One plan; `include_context=true` adds exactly what was sent to the LLM."""
    return service.get_plan(db, user, plan_id, include_context=include_context)
