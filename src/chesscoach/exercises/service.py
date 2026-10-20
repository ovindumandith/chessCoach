"""Exercise lifecycle: select from analyzed games -> hint -> attempt -> solved/failed/revealed.

Solutions stay server-side until the exercise is finished. Illegal moves are rejected
before anything is recorded. Exercise results feed progress and coaching context, but a
single exercise never changes a skill profile (project.md §11).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chesscoach.analysis.scores import Evaluation
from chesscoach.classification.classifier import CLASSIFIER_VERSION
from chesscoach.classification.service import latest_evidence
from chesscoach.coaching.retrieval import build_context, format_eval
from chesscoach.core.access import require_own_student_record, require_student_access
from chesscoach.core.audit import record_audit
from chesscoach.core.errors import ConflictError, NotFoundError, ValidationFailedError
from chesscoach.db.enums import (
    ExercisePurpose,
    ExerciseStatus,
    MappingStatus,
    ReviewStatus,
    ValidationStatus,
)
from chesscoach.db.models import (
    Exercise,
    ExerciseAttempt,
    Game,
    ProfileSnapshot,
    User,
    WeaknessObservation,
)
from chesscoach.db.types import utcnow
from chesscoach.exercises.history import FINISHED, exercise_stats, with_first_attempts
from chesscoach.exercises.selection import (
    SELECTION_VERSION,
    PositionInput,
    build_candidate,
    is_exercisable,
    parse_move,
    relevant,
    to_san,
)

MAX_COUNT = 10


def create_exercises(
    db: Session,
    user: User,
    student_id: uuid.UUID,
    *,
    skill_code: str | None = None,
    subskill_code: str | None = None,
    count: int = 5,
) -> list[Exercise]:
    require_student_access(db, user, student_id)
    if skill_code is None:
        ctx = build_context(db, student_id)  # top trainable skill from the profile
        skill_code, subskill_code = ctx.objective.skill_code, ctx.objective.subskill_code
    if not is_exercisable(skill_code, subskill_code):
        raise ConflictError(
            "This skill cannot be practised with board positions",
            details={"skill_code": skill_code, "subskill_code": subskill_code},
        )
    count = max(1, min(count, MAX_COUNT))

    labelled = _labelled_moves(db, student_id, skill_code, subskill_code)
    used = set(
        db.scalars(
            select(Exercise.source_move_analysis_id).where(Exercise.student_id == student_id)
        )
    )
    review, practice = [], []
    for game in db.scalars(
        select(Game).where(
            Game.student_id == student_id,
            Game.mapping_status.in_((MappingStatus.MAPPED, MappingStatus.CONFIRMED)),
        )
    ):
        try:
            _, _, moves = latest_evidence(db, game)
        except ConflictError:
            continue
        for m in moves:
            if m.id in used:
                continue
            p = _position(m, game)
            severity = labelled.get(m.id)
            if not relevant(p, skill_code, subskill_code, labelled=severity is not None):
                continue
            candidate = build_candidate(p, subskill_code)
            if candidate is None:
                continue
            if severity is not None:
                review.append((severity, candidate))
            else:
                practice.append((p.gap or 1.0, candidate))
    review.sort(key=lambda x: -x[0])
    practice.sort(key=lambda x: -x[0])
    chosen = [(ExercisePurpose.REVIEW, c) for _, c in review]
    chosen += [(ExercisePurpose.PRACTICE, c) for _, c in practice]
    chosen = chosen[:count]
    if not chosen:
        raise ConflictError(
            "No positions in this student's games have an unambiguous solution for this skill yet",
            details={"skill_code": skill_code, "subskill_code": subskill_code},
        )

    exercises = []
    for purpose, c in chosen:
        ex = Exercise(
            student_id=student_id,
            skill_code=skill_code,
            subskill_code=subskill_code,
            purpose=purpose,
            source_game_id=uuid.UUID(c.position.game_id),
            source_move_analysis_id=uuid.UUID(c.position.move_analysis_id),
            start_fen=c.position.fen,
            accepted_moves=c.accepted_moves,
            solution_source="stockfish_analysis",
            validation_status=ValidationStatus.VALID,  # legality checked in build_candidate
            difficulty=c.difficulty,
            explanation=c.explanation,
            details=c.details,
        )
        db.add(ex)
        exercises.append(ex)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        action="exercises.create",
        entity_type="student",
        entity_id=student_id,
        details={
            "skill_code": skill_code,
            "subskill_code": subskill_code,
            "count": len(exercises),
            "selection_version": SELECTION_VERSION,
        },
    )
    db.commit()
    return exercises


def get_exercise(db: Session, user: User, exercise_id: uuid.UUID) -> Exercise:
    ex = db.get(Exercise, exercise_id)
    if ex is None:
        raise NotFoundError("Exercise not found")
    require_student_access(db, user, ex.student_id)
    return ex


def list_exercises(
    db: Session, user: User, student_id: uuid.UUID, *, status=None, limit: int, offset: int
) -> tuple[list[Exercise], int]:
    require_student_access(db, user, student_id)
    query = select(Exercise).where(Exercise.student_id == student_id)
    if status is not None:
        query = query.where(Exercise.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Exercise.created_at.desc()).limit(limit).offset(offset))
    return list(rows), total


def attempts_for(db: Session, exercise_id: uuid.UUID) -> list[ExerciseAttempt]:
    return list(
        db.scalars(
            select(ExerciseAttempt)
            .where(ExerciseAttempt.exercise_id == exercise_id)
            .order_by(ExerciseAttempt.attempt_number)
        )
    )


def next_hint(db: Session, user: User, exercise_id: uuid.UUID) -> tuple[Exercise, str]:
    ex = _open_for_student(db, user, exercise_id)
    hints = ex.details.get("hints", [])
    if ex.hints_given >= len(hints):
        raise ConflictError("No more hints for this exercise")
    hint = hints[ex.hints_given]
    ex.hints_given += 1
    db.commit()
    return ex, hint


@dataclass
class AttemptResult:
    exercise: Exercise
    attempt: ExerciseAttempt
    attempts_left: int


def record_attempt(
    db: Session, user: User, exercise_id: uuid.UUID, *, move: str, time_taken_ms: int | None = None
) -> AttemptResult:
    ex = _open_for_student(db, user, exercise_id)
    parsed = parse_move(ex.start_fen, move)
    if parsed is None:  # validated before anything is recorded
        raise ValidationFailedError(
            "That move is not legal in this position", details={"move": move}
        )
    previous = (
        db.scalar(
            select(func.count())
            .select_from(ExerciseAttempt)
            .where(ExerciseAttempt.exercise_id == ex.id)
        )
        or 0
    )
    correct = parsed.uci() in ex.accepted_moves
    attempt = ExerciseAttempt(
        exercise_id=ex.id,
        student_id=ex.student_id,
        submitted_move=parsed.uci(),
        attempt_number=previous + 1,
        is_correct=correct,
        hints_used=ex.hints_given,
        time_taken_ms=time_taken_ms,
    )
    db.add(attempt)
    if correct:
        ex.status, ex.finished_at = ExerciseStatus.SOLVED, utcnow()
    elif attempt.attempt_number >= ex.max_attempts:
        ex.status, ex.finished_at = ExerciseStatus.FAILED, utcnow()
    db.commit()
    return AttemptResult(
        ex,
        attempt,
        max(0, ex.max_attempts - attempt.attempt_number) if ex.status == ExerciseStatus.OPEN else 0,
    )


def reveal(db: Session, user: User, exercise_id: uuid.UUID) -> Exercise:
    ex = _open_for_student(db, user, exercise_id)
    ex.status, ex.finished_at = ExerciseStatus.REVEALED, utcnow()
    db.commit()
    return ex


def solution_view(ex: Exercise) -> dict | None:
    """The solution, only once the exercise is finished."""
    if ex.status not in FINISHED:
        return None
    return {
        "accepted_moves_uci": ex.accepted_moves,
        "accepted_moves_san": [to_san(ex.start_fen, m) for m in ex.accepted_moves],
        "explanation": ex.explanation,
        "game_move": ex.details.get("game_move"),
    }


# --------------------------------------------------------------------------- history & progress


def progress(db: Session, user: User, student_id: uuid.UUID) -> dict:
    require_student_access(db, user, student_id)
    by_skill: dict[tuple, list] = {}
    for e, a in with_first_attempts(db, student_id):
        by_skill.setdefault((e.skill_code, e.subskill_code), []).append((e, a))

    trends: dict[tuple, list] = {}
    snapshots = db.scalars(
        select(ProfileSnapshot)
        .where(ProfileSnapshot.student_id == student_id, ProfileSnapshot.cutoff_date.is_(None))
        .order_by(ProfileSnapshot.profile_version)
    )
    for snap in snapshots:
        for row in snap.skills:
            if row.error_count or (row.skill_code, row.subskill_code) in trends:
                trends.setdefault((row.skill_code, row.subskill_code), []).append(
                    {
                        "profile_version": snap.profile_version,
                        "generated_at": snap.generated_at.isoformat(),
                        "state": row.state.value,
                        "error_rate": row.error_rate,
                        "games_affected": row.games_affected,
                        "priority_score": row.priority_score,
                    }
                )
    keys = sorted(set(by_skill) | set(trends), key=lambda k: (k[0], k[1] or ""))
    return {
        "student_id": str(student_id),
        "note": (
            "Exercise accuracy is shown alongside game evidence; it does not change "
            "skill profiles on its own."
        ),
        "skills": [
            {
                "skill_code": k[0],
                "subskill_code": k[1],
                "exercises": exercise_stats(by_skill.get(k, [])),
                "profile_trend": trends.get(k, []),
            }
            for k in keys
        ],
    }


# --------------------------------------------------------------------------- helpers


def _open_for_student(db: Session, user: User, exercise_id: uuid.UUID) -> Exercise:
    ex = db.get(Exercise, exercise_id)
    if ex is None:
        raise NotFoundError("Exercise not found")
    require_own_student_record(db, user, ex.student_id)
    if ex.status != ExerciseStatus.OPEN:
        raise ConflictError(
            "This exercise is already finished", details={"status": ex.status.value}
        )
    return ex


def _labelled_moves(
    db: Session, student_id: uuid.UUID, skill_code: str, subskill_code: str | None
) -> dict[uuid.UUID, float]:
    """move_analysis_id -> severity of current findings for this skill (not rejected)."""
    rows = db.execute(
        select(WeaknessObservation.move_analysis_id, WeaknessObservation.severity).where(
            WeaknessObservation.student_id == student_id,
            WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
            WeaknessObservation.review_status != ReviewStatus.REJECTED,
            WeaknessObservation.skill_code == skill_code,
            WeaknessObservation.subskill_code.is_(None)
            if subskill_code is None
            else WeaknessObservation.subskill_code == subskill_code,
        )
    )
    out: dict[uuid.UUID, float] = {}
    for move_id, severity in rows:
        out[move_id] = max(out.get(move_id, 0.0), severity or 0.0)
    return out


def _position(m, game: Game) -> PositionInput:
    eval_before = (
        Evaluation(mate=m.eval_before_mate)
        if m.eval_before_mate is not None
        else Evaluation(cp=m.eval_before_cp)
    )
    features = m.features or {}
    return PositionInput(
        move_analysis_id=str(m.id),
        game_id=str(game.id),
        ply=m.ply,
        fen=m.fen_before,
        phase=m.phase.value,
        played_uci=m.uci_move,
        played_san=m.san_move,
        best_uci=m.best_move_uci,
        eval_before=eval_before,
        eval_after_text=format_eval(m.eval_after_cp, m.eval_after_mate, after_move=True),
        gap=features.get("only_move_gap_wp"),
        legal_moves=features.get("legal_moves"),
        best_line_san=features.get("pv_san", []),
    )
