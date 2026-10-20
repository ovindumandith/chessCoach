"""Exercise outcomes for progress views and coaching context. Models only, no services."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.db.enums import ExerciseStatus
from chesscoach.db.models import Exercise, ExerciseAttempt

FINISHED = (ExerciseStatus.SOLVED, ExerciseStatus.FAILED, ExerciseStatus.REVEALED)


def exercise_stats(attempted: list[tuple[Exercise, ExerciseAttempt | None]]) -> dict:
    tried = [(e, a) for e, a in attempted if a is not None]
    first = sum(1 for _, a in tried if a.attempt_number == 1 and a.is_correct)
    return {
        "assigned": len(attempted),
        "attempted": len(tried),
        "solved_first_try": first,
        "solved": sum(1 for e, _ in tried if e.status == ExerciseStatus.SOLVED),
        "failed": sum(1 for e, _ in attempted if e.status == ExerciseStatus.FAILED),
        "revealed": sum(1 for e, _ in attempted if e.status == ExerciseStatus.REVEALED),
        "first_try_accuracy": round(first / len(tried), 4) if tried else None,
    }


def with_first_attempts(
    db: Session, student_id: uuid.UUID
) -> list[tuple[Exercise, ExerciseAttempt | None]]:
    exercises = list(
        db.scalars(
            select(Exercise).where(Exercise.student_id == student_id).order_by(Exercise.created_at)
        )
    )
    firsts = {
        a.exercise_id: a
        for a in db.scalars(
            select(ExerciseAttempt).where(
                ExerciseAttempt.student_id == student_id, ExerciseAttempt.attempt_number == 1
            )
        )
    }
    return [(e, firsts.get(e.id)) for e in exercises]


def exercise_history(db: Session, student_id: uuid.UUID, limit: int = 10) -> list[dict]:
    """Recent finished exercises for coaching context (no solutions, just outcomes)."""
    rows = [(e, a) for e, a in with_first_attempts(db, student_id) if e.status in FINISHED]
    rows.sort(key=lambda r: r[0].finished_at or r[0].created_at, reverse=True)
    return [
        {
            "skill_code": e.skill_code,
            "subskill_code": e.subskill_code,
            "purpose": e.purpose.value,
            "status": e.status.value,
            "first_try_correct": bool(a and a.attempt_number == 1 and a.is_correct),
            "hints_used": e.hints_given,
            "date": (e.finished_at or e.created_at).date().isoformat(),
        }
        for e, a in rows[:limit]
    ]
