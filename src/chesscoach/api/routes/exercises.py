import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from chesscoach.api.deps import CurrentUser, DbSession, rate_limited
from chesscoach.api.schemas import (
    AttemptOut,
    AttemptRequest,
    ExerciseAttemptOut,
    ExerciseCreate,
    ExerciseOut,
    HintOut,
    Page,
)
from chesscoach.db.enums import ExerciseStatus
from chesscoach.exercises import service
from chesscoach.exercises.selection import side_to_move, to_san

router = APIRouter(tags=["exercises"])


def exercise_out(db, ex) -> ExerciseOut:
    side = side_to_move(ex.start_fen)
    return ExerciseOut(
        id=ex.id,
        student_id=ex.student_id,
        skill_code=ex.skill_code,
        subskill_code=ex.subskill_code,
        purpose=ex.purpose,
        status=ex.status,
        start_fen=ex.start_fen,
        side_to_move=side,
        prompt=f"{side.capitalize()} to move. Find the best move.",
        difficulty=ex.difficulty,
        max_attempts=ex.max_attempts,
        attempts=[
            ExerciseAttemptOut(
                attempt_number=a.attempt_number,
                move_uci=a.submitted_move,
                move_san=to_san(ex.start_fen, a.submitted_move),
                is_correct=a.is_correct,
                hints_used=a.hints_used,
                time_taken_ms=a.time_taken_ms,
            )
            for a in service.attempts_for(db, ex.id)
        ],
        hints_given=ex.hints_given,
        hints_available=len(ex.details.get("hints", [])),
        created_at=ex.created_at,
        finished_at=ex.finished_at,
        solution=service.solution_view(ex),
    )


@router.post(
    "/students/{student_id}/exercises",
    response_model=list[ExerciseOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limited("exercises", lambda s: s.rate_limit_exercises_per_hour)],
)
def create_exercises(
    student_id: uuid.UUID, db: DbSession, user: CurrentUser, body: ExerciseCreate | None = None
) -> list[ExerciseOut]:
    """Select exercises from the student's own analyzed games (review first, then practice)."""
    body = body or ExerciseCreate()
    rows = service.create_exercises(
        db,
        user,
        student_id,
        skill_code=body.skill_code,
        subskill_code=body.subskill_code,
        count=body.count,
    )
    return [exercise_out(db, ex) for ex in rows]


@router.get("/students/{student_id}/exercises", response_model=Page[ExerciseOut])
def list_exercises(
    student_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    status: ExerciseStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ExerciseOut]:
    rows, total = service.list_exercises(
        db, user, student_id, status=status, limit=limit, offset=offset
    )
    return Page(
        items=[exercise_out(db, ex) for ex in rows], total=total, limit=limit, offset=offset
    )


@router.get("/exercises/{exercise_id}", response_model=ExerciseOut)
def get_exercise(exercise_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ExerciseOut:
    return exercise_out(db, service.get_exercise(db, user, exercise_id))


@router.post("/exercises/{exercise_id}/hint", response_model=HintOut)
def hint(exercise_id: uuid.UUID, db: DbSession, user: CurrentUser) -> HintOut:
    ex, text = service.next_hint(db, user, exercise_id)
    total = len(ex.details.get("hints", []))
    return HintOut(hint=text, hints_given=ex.hints_given, hints_remaining=total - ex.hints_given)


@router.post(
    "/exercises/{exercise_id}/attempts",
    response_model=AttemptOut,
    status_code=status.HTTP_201_CREATED,
)
def attempt(
    exercise_id: uuid.UUID, body: AttemptRequest, db: DbSession, user: CurrentUser
) -> AttemptOut:
    """Record a move. Illegal moves are rejected (422) and not recorded."""
    result = service.record_attempt(
        db, user, exercise_id, move=body.move, time_taken_ms=body.time_taken_ms
    )
    return AttemptOut(
        correct=result.attempt.is_correct,
        attempts_left=result.attempts_left,
        exercise=exercise_out(db, result.exercise),
    )


@router.post("/exercises/{exercise_id}/reveal", response_model=ExerciseOut)
def reveal(exercise_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ExerciseOut:
    return exercise_out(db, service.reveal(db, user, exercise_id))


@router.get("/students/{student_id}/progress")
def progress(student_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    """Exercise accuracy and profile trend per skill."""
    return service.progress(db, user, student_id)
