"""Build the compact, evidence-only coaching context from the latest profile snapshot.

Only 2-5 representative positions are sent, never the whole game archive. Every position
is copied from stored analysis, so anything the LLM says about it can be checked.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.classification.classifier import CLASSIFIER_VERSION
from chesscoach.classification.taxonomy import UNCLASSIFIED, get_taxonomy
from chesscoach.coaching.schemas import CoachingContext, EvidencePosition, SkillFocus
from chesscoach.core.errors import ConflictError, NotFoundError
from chesscoach.db.enums import ReviewStatus
from chesscoach.db.models import (
    CoachingSession,
    Game,
    MoveAnalysis,
    ProfileSnapshot,
    Student,
    StudentSkillProfile,
    WeaknessObservation,
)
from chesscoach.exercises.history import exercise_history

MAX_POSITIONS = 5
PREVIOUS_LESSONS = 3


def format_eval(cp: int | None, mate: int | None, *, after_move: bool = False) -> str:
    if mate is not None:
        if mate == 0 and after_move:
            return "checkmate delivered"
        return f"mate in {mate}" if mate > 0 else f"mated in {-mate}"
    return f"{cp / 100:+.2f}"


def skill_name(skill_code: str, subskill_code: str | None) -> str:
    taxonomy = get_taxonomy()
    if skill_code in taxonomy.special:
        return taxonomy.special[skill_code].name
    category = taxonomy.categories.get(skill_code)
    if category is None:
        return skill_code
    if subskill_code and subskill_code in category.subskills:
        return f"{category.name}: {category.subskills[subskill_code].name}"
    return category.name


def _focus(row: StudentSkillProfile) -> SkillFocus:
    return SkillFocus(
        skill_code=row.skill_code,
        subskill_code=row.subskill_code,
        skill_name=skill_name(row.skill_code, row.subskill_code),
        state=row.state.value,
        error_count=row.error_count,
        games_affected=row.games_affected,
        opportunity_count=row.opportunity_count,
        error_rate=row.error_rate,
        priority_score=row.priority_score,
        provisional=bool(row.evidence_summary.get("provisional")),
    )


def _actionable(rows: list[StudentSkillProfile]) -> list[StudentSkillProfile]:
    """Trainable skills with evidence. Unexplained errors are never a lesson objective,
    even in snapshots built before that rule existed."""
    return sorted(
        (
            r
            for r in rows
            if r.priority_score and r.error_count > 0 and r.skill_code != UNCLASSIFIED
        ),
        key=lambda r: -r.priority_score,
    )


def build_context(
    db: Session,
    student_id: uuid.UUID,
    *,
    skill_code: str | None = None,
    subskill_code: str | None = None,
) -> CoachingContext:
    student = db.get(Student, student_id)
    if student is None:
        raise NotFoundError("Student not found")
    snapshot = db.scalars(
        select(ProfileSnapshot)
        .where(ProfileSnapshot.student_id == student_id, ProfileSnapshot.cutoff_date.is_(None))
        .order_by(ProfileSnapshot.profile_version.desc())
        .limit(1)
    ).first()
    if snapshot is None:
        raise ConflictError("Build the student's profile before generating a lesson")

    ranked = _actionable(snapshot.skills)
    if skill_code == UNCLASSIFIED:
        raise ConflictError(
            "Unexplained errors are a review queue, not a lesson topic. "
            "Review and label them first."
        )
    if skill_code:
        chosen = next(
            (
                r
                for r in snapshot.skills
                if r.skill_code == skill_code
                and (subskill_code is None or r.subskill_code == subskill_code)
            ),
            None,
        )
        if chosen is None or chosen.error_count == 0:
            raise ConflictError(
                "The profile has no evidence for the requested skill",
                details={"skill_code": skill_code, "subskill_code": subskill_code},
            )
    elif ranked:
        chosen = ranked[0]
    else:
        raise ConflictError("The profile has no actionable weakness to coach yet")
    secondary = next((r for r in ranked if r.id != chosen.id), None)

    positions = _positions(db, student_id, chosen)
    if not positions:
        raise ConflictError("No usable evidence positions for this skill")

    lessons = db.scalars(
        select(CoachingSession)
        .where(CoachingSession.student_id == student_id)
        .order_by(CoachingSession.created_at.desc())
        .limit(PREVIOUS_LESSONS)
    ).all()
    return CoachingContext(
        student_id=str(student_id),
        student_level=student.skill_level,
        rating_estimate=student.rating_estimate,
        learning_preferences=student.learning_preferences or {},
        profile_version=snapshot.profile_version,
        objective=_focus(chosen),
        secondary=_focus(secondary) if secondary else None,
        positions=positions,
        previous_lessons=[
            {
                "date": s.created_at.date().isoformat(),
                "objective": s.response_json.get("objective"),
                "skill_code": s.response_json.get("skill_code"),
            }
            for s in lessons
        ],
        exercise_history=exercise_history(db, student_id),
    )


def _positions(
    db: Session, student_id: uuid.UUID, row: StudentSkillProfile
) -> list[EvidencePosition]:
    """Profile examples first (highest severity, one per game), then other findings."""
    ids = [uuid.UUID(i) for i in row.evidence_summary.get("example_observation_ids", [])]
    query = (
        select(WeaknessObservation, MoveAnalysis, Game)
        .join(MoveAnalysis, MoveAnalysis.id == WeaknessObservation.move_analysis_id)
        .join(Game, Game.id == WeaknessObservation.game_id)
        .where(
            WeaknessObservation.student_id == student_id,  # ownership enforced in the query
            WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
            WeaknessObservation.review_status != ReviewStatus.REJECTED,
            WeaknessObservation.skill_code == row.skill_code,
            WeaknessObservation.subskill_code.is_(None)
            if row.subskill_code is None
            else WeaknessObservation.subskill_code == row.subskill_code,
        )
    )
    rows = db.execute(query).all()
    rank = {oid: i for i, oid in enumerate(ids)}
    rows.sort(key=lambda r: (rank.get(r[0].id, len(rank)), -(r[0].severity or 0)))

    out, seen_moves = [], set()
    for obs, move, game in rows:
        if move.id in seen_moves:
            continue
        seen_moves.add(move.id)
        pv = move.features.get("pv_san", [])
        out.append(
            EvidencePosition(
                observation_id=str(obs.id),
                game_id=str(game.id),
                ply=move.ply,
                move_number=(move.ply + 1) // 2,
                student_color=game.student_color.value if game.student_color else "unknown",
                fen=move.fen_before,
                played_move_san=move.san_move,
                played_move_uci=move.uci_move,
                engine_best_move_san=pv[0] if pv else None,
                engine_best_move_uci=move.best_move_uci,
                engine_best_line_san=pv,
                opponent_best_reply_san=move.features.get("refutation_san", []),
                eval_before=format_eval(move.eval_before_cp, move.eval_before_mate),
                eval_after=format_eval(move.eval_after_cp, move.eval_after_mate, after_move=True),
                win_probability_loss=round(move.win_prob_loss or 0.0, 4),
                phase=move.phase.value,
                evidence_type=obs.evidence_type.value,
                motif_kind=obs.details.get("motif_kind"),
                review_status=obs.review_status.value,
            )
        )
        if len(out) == MAX_POSITIONS:
            break
    return out
