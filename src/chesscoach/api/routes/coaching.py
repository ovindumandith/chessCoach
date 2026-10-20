import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from chesscoach.api.deps import CurrentUser, DbSession, rate_limited
from chesscoach.api.schemas import CoachingSessionOut, LessonOut, LessonRequest, Page
from chesscoach.coaching import service

router = APIRouter(prefix="/students/{student_id}/coaching", tags=["coaching"])


@router.post(
    "/lessons",
    response_model=LessonOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limited("lessons", lambda s: s.rate_limit_lessons_per_hour)],
)
def generate_lesson(
    student_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    body: LessonRequest | None = None,
) -> LessonOut:
    """Personalized lesson from the latest profile. LLM output is shown only after chess and
    evidence validation; otherwise a deterministic template lesson is returned."""
    result = service.generate_lesson(
        db,
        user,
        student_id,
        skill_code=body.skill_code if body else None,
        subskill_code=body.subskill_code if body else None,
    )
    return LessonOut(
        session=CoachingSessionOut.model_validate(result.session),
        used_fallback=result.used_fallback,
        lesson=result.response,
    )


@router.get("/sessions", response_model=Page[CoachingSessionOut])
def list_sessions(
    student_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CoachingSessionOut]:
    rows, total = service.list_sessions(db, user, student_id, limit=limit, offset=offset)
    return Page(
        items=[CoachingSessionOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
