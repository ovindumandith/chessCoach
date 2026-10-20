"""Classification orchestration and coach review. Reads analysis evidence, never the engine."""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from chesscoach.analysis.scores import Evaluation
from chesscoach.classification.classifier import (
    CLASSIFIER_VERSION,
    GameContext,
    MoveEvidence,
    classify_move,
    parse_base_time,
    versions,
)
from chesscoach.classification.taxonomy import UNCLASSIFIED, get_taxonomy
from chesscoach.core.access import get_access_level, require_admin, require_student_access
from chesscoach.core.audit import record_audit
from chesscoach.core.errors import ConflictError, NotFoundError, ValidationFailedError
from chesscoach.db.enums import (
    AccessLevel,
    AnalysisPass,
    EvidenceType,
    JobStatus,
    ReviewStatus,
    UserRole,
)
from chesscoach.db.models import (
    AnalysisRun,
    Game,
    MoveAnalysis,
    SkillOpportunity,
    User,
    WeaknessObservation,
)
from chesscoach.db.types import utcnow


@dataclass
class ClassifyResult:
    game_id: uuid.UUID
    baseline_run_id: uuid.UUID
    critical_run_id: uuid.UUID | None
    moves_classified: int
    observations: int
    opportunities: int
    preserved_reviewed: int
    carried_reviews: int = 0
    classifier_version: str = CLASSIFIER_VERSION


def latest_evidence(
    db: Session, game: Game
) -> tuple[AnalysisRun, AnalysisRun | None, list[MoveAnalysis]]:
    """Latest completed baseline run, with deeper critical-pass rows replacing their plies."""
    baseline = db.scalars(
        select(AnalysisRun)
        .where(
            AnalysisRun.game_id == game.id,
            AnalysisRun.pass_type == AnalysisPass.BASELINE,
            AnalysisRun.status == JobStatus.COMPLETED,
        )
        .order_by(AnalysisRun.completed_at.desc())
        .limit(1)
    ).first()
    if baseline is None:
        raise ConflictError("Game has no completed analysis to classify")
    critical = next(
        (
            r
            for r in db.scalars(
                select(AnalysisRun)
                .where(
                    AnalysisRun.game_id == game.id,
                    AnalysisRun.pass_type == AnalysisPass.CRITICAL,
                    AnalysisRun.status == JobStatus.COMPLETED,
                )
                .order_by(AnalysisRun.completed_at.desc())
            )
            if r.configuration.get("parent_run_id") == str(baseline.id)
        ),
        None,
    )
    by_ply = {m.ply: m for m in _run_moves(db, baseline.id)}
    if critical is not None:
        by_ply.update({m.ply: m for m in _run_moves(db, critical.id)})
    return baseline, critical, [by_ply[p] for p in sorted(by_ply)]


def classify_game(db: Session, game_id: uuid.UUID, *, actor: User | None = None) -> ClassifyResult:
    """(Re)derive candidate observations for a game. Idempotent per classifier version.

    Coach-reviewed observations are never deleted or duplicated.
    """
    game = db.get(Game, game_id)
    if game is None:
        raise NotFoundError("Game not found")
    if actor is not None:
        require_student_access(db, actor, game.student_id, coach_only=True)

    baseline, critical, moves = latest_evidence(db, game)
    taxonomy = get_taxonomy()
    reviewed = db.scalars(
        select(WeaknessObservation).where(
            WeaknessObservation.game_id == game.id,
            WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
            WeaknessObservation.review_status != ReviewStatus.CANDIDATE,
        )
    ).all()
    reviewed_keys = set()
    for obs in reviewed:
        reviewed_keys.add(
            _key(obs.move_analysis_id, obs.skill_code, obs.subskill_code, obs.evidence_type)
        )
        original = obs.details.get("original")
        if original:
            reviewed_keys.add(
                _key(
                    obs.move_analysis_id,
                    original["skill_code"],
                    original["subskill_code"],
                    EvidenceType(original["evidence_type"]),
                )
            )

    carry = _prior_version_reviews(db, game.id)

    db.execute(
        delete(WeaknessObservation).where(
            WeaknessObservation.game_id == game.id,
            WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
            WeaknessObservation.review_status == ReviewStatus.CANDIDATE,
        )
    )
    db.execute(
        delete(SkillOpportunity).where(
            SkillOpportunity.game_id == game.id,
            SkillOpportunity.classifier_version == CLASSIFIER_VERSION,
        )
    )

    ctx = GameContext(base_time_seconds=parse_base_time(game.time_control))
    n_obs = n_opp = n_carried = 0
    for move in moves:
        result = classify_move(_evidence(move), ctx)
        for draft in result.observations:
            taxonomy.require_valid(draft.skill_code, draft.subskill_code)
            if (
                _key(move.id, draft.skill_code, draft.subskill_code, draft.evidence_type)
                in reviewed_keys
            ):
                continue
            obs = WeaknessObservation(
                student_id=game.student_id,
                game_id=game.id,
                move_analysis_id=move.id,
                skill_code=draft.skill_code,
                subskill_code=draft.subskill_code,
                evidence_type=draft.evidence_type,
                severity=round(draft.severity, 6),
                confidence=draft.confidence,
                classifier_version=CLASSIFIER_VERSION,
                taxonomy_version=taxonomy.version,
                details={**draft.details, "ply": move.ply, **versions()},
            )
            prior = carry.get(
                (move.ply, draft.skill_code, draft.subskill_code, draft.evidence_type.value)
            )
            if prior is not None:
                _apply_prior_review(obs, prior)
                n_carried += 1
            db.add(obs)
            n_obs += 1
        for opp in result.opportunities:
            db.add(
                SkillOpportunity(
                    student_id=game.student_id,
                    game_id=game.id,
                    move_analysis_id=move.id,
                    skill_code=opp.skill_code,
                    subskill_code=opp.subskill_code,
                    outcome=opp.outcome,
                    classifier_version=CLASSIFIER_VERSION,
                    details={**opp.details, "ply": move.ply},
                )
            )
            n_opp += 1

    if actor is not None:
        record_audit(
            db,
            actor_user_id=actor.id,
            action="classification.run",
            entity_type="game",
            entity_id=game.id,
            details={"classifier_version": CLASSIFIER_VERSION},
        )
    db.commit()
    return ClassifyResult(
        game_id=game.id,
        baseline_run_id=baseline.id,
        critical_run_id=critical.id if critical else None,
        moves_classified=len(moves),
        observations=n_obs,
        opportunities=n_opp,
        preserved_reviewed=len(reviewed),
        carried_reviews=n_carried,
    )


# --------------------------------------------------------------------------- read & review


@dataclass
class ObservationView:
    observation: WeaknessObservation
    move: MoveAnalysis
    game: Game


def list_weaknesses(
    db: Session,
    user: User,
    student_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
    skill_code: str | None = None,
    evidence_type: EvidenceType | None = None,
    review_status: ReviewStatus | None = None,
) -> tuple[list[ObservationView], int]:
    require_student_access(db, user, student_id)
    query = (
        select(WeaknessObservation, MoveAnalysis, Game)
        .join(MoveAnalysis, MoveAnalysis.id == WeaknessObservation.move_analysis_id)
        .join(Game, Game.id == WeaknessObservation.game_id)
        .where(
            WeaknessObservation.student_id == student_id,
            # Older-version rows are kept as history but are not current findings.
            WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
        )
    )
    if skill_code:
        query = query.where(WeaknessObservation.skill_code == skill_code)
    if evidence_type:
        query = query.where(WeaknessObservation.evidence_type == evidence_type)
    if review_status:
        query = query.where(WeaknessObservation.review_status == review_status)
    if _is_student_viewer(db, user, student_id):
        # Students never see findings their coach rejected.
        query = query.where(WeaknessObservation.review_status != ReviewStatus.REJECTED)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.order_by(
            WeaknessObservation.severity.desc().nulls_last(), WeaknessObservation.created_at.desc()
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return [ObservationView(o, m, g) for o, m, g in rows], total


def get_observation_view(db: Session, observation_id: uuid.UUID) -> ObservationView:
    """Callers must already have checked access to the observation's student."""
    row = db.execute(
        select(WeaknessObservation, MoveAnalysis, Game)
        .join(MoveAnalysis, MoveAnalysis.id == WeaknessObservation.move_analysis_id)
        .join(Game, Game.id == WeaknessObservation.game_id)
        .where(WeaknessObservation.id == observation_id)
    ).one_or_none()
    if row is None:
        raise NotFoundError("Observation not found")
    return ObservationView(*row)


def review_observation(
    db: Session,
    user: User,
    observation_id: uuid.UUID,
    *,
    action: str,
    skill_code: str | None = None,
    subskill_code: str | None = None,
    note: str | None = None,
) -> WeaknessObservation:
    obs = db.get(WeaknessObservation, observation_id)
    if obs is None:
        raise NotFoundError("Observation not found")
    # Findings are not reviewed in the product: students see them, coaches monitor. Manual
    # labelling stays available to administrators for research (gold labels, evaluation).
    require_admin(user)

    previous = {
        "review_status": obs.review_status.value,
        "skill_code": obs.skill_code,
        "subskill_code": obs.subskill_code,
    }
    if action == "confirm":
        obs.review_status = ReviewStatus.CONFIRMED
    elif action == "reject":
        obs.review_status = ReviewStatus.REJECTED
    elif action == "correct":
        if not skill_code:
            raise ValidationFailedError("A correction needs a skill_code")
        try:
            get_taxonomy().require_valid(skill_code, subskill_code)
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc
        details = dict(obs.details)
        details.setdefault(
            "original",
            {
                "skill_code": obs.skill_code,
                "subskill_code": obs.subskill_code,
                "evidence_type": obs.evidence_type.value,
            },
        )
        obs.details = details
        obs.skill_code = skill_code
        obs.subskill_code = subskill_code
        obs.review_status = ReviewStatus.CORRECTED
    else:
        raise ValidationFailedError(f"Unknown review action {action!r}")

    obs.reviewed_by = user.id
    obs.reviewed_at = utcnow()
    obs.review_note = note
    record_audit(
        db,
        actor_user_id=user.id,
        action=f"observation.{action}",
        entity_type="weakness_observation",
        entity_id=obs.id,
        details={
            "previous": previous,
            "skill_code": obs.skill_code,
            "subskill_code": obs.subskill_code,
        },
    )
    db.commit()
    return obs


# --------------------------------------------------------------------------- helpers


def _prior_version_reviews(db: Session, game_id: uuid.UUID) -> dict[tuple, WeaknessObservation]:
    """Coach reviews made under OTHER classifier versions, keyed by what the classifier
    originally said: (ply, skill, subskill, evidence type).

    Keyed by ply rather than move_analysis_id so reviews also survive a forced re-analysis.
    The most recent review of a finding wins.
    """
    rows = db.scalars(
        select(WeaknessObservation)
        .where(
            WeaknessObservation.game_id == game_id,
            WeaknessObservation.classifier_version != CLASSIFIER_VERSION,
            WeaknessObservation.review_status != ReviewStatus.CANDIDATE,
        )
        .order_by(WeaknessObservation.reviewed_at.asc().nulls_first())
    ).all()
    carry: dict[tuple, WeaknessObservation] = {}
    for obs in rows:
        ply = obs.details.get("ply")
        if ply is None:
            continue
        original = obs.details.get("original")
        if original:
            key = (
                ply,
                original["skill_code"],
                original["subskill_code"],
                original["evidence_type"],
            )
        else:
            key = (ply, obs.skill_code, obs.subskill_code, obs.evidence_type.value)
        carry[key] = obs
    return carry


def _apply_prior_review(obs: WeaknessObservation, prior: WeaknessObservation) -> None:
    """Re-apply a coach's earlier decision to the same finding from a new classifier."""
    obs.review_status = prior.review_status
    obs.reviewed_by = prior.reviewed_by
    obs.reviewed_at = prior.reviewed_at
    obs.review_note = prior.review_note
    details = {
        **obs.details,
        "review_carried_from": {
            "observation_id": str(prior.id),
            "classifier_version": prior.classifier_version,
        },
    }
    if prior.review_status == ReviewStatus.CORRECTED:
        details["original"] = {
            "skill_code": obs.skill_code,
            "subskill_code": obs.subskill_code,
            "evidence_type": obs.evidence_type.value,
        }
        obs.skill_code = prior.skill_code
        obs.subskill_code = prior.subskill_code
    obs.details = details


def _run_moves(db: Session, run_id: uuid.UUID) -> list[MoveAnalysis]:
    return list(db.scalars(select(MoveAnalysis).where(MoveAnalysis.analysis_run_id == run_id)))


def _evidence(m: MoveAnalysis) -> MoveEvidence:
    eval_before = (
        Evaluation(mate=m.eval_before_mate)
        if m.eval_before_mate is not None
        else Evaluation(cp=m.eval_before_cp)
    )
    return MoveEvidence(
        fen_before=m.fen_before,
        fen_after=m.fen_after,
        uci_move=m.uci_move,
        phase=m.phase,
        eval_before=eval_before,
        best_move_uci=m.best_move_uci,
        win_prob_loss=m.win_prob_loss or 0.0,
        features=m.features or {},
        clock_before_ms=m.clock_before_ms,
        cp_loss=m.best_move_loss_cp,
    )


def _key(move_id, skill, subskill, evidence_type) -> tuple:
    return (str(move_id), skill, subskill, EvidenceType(evidence_type).value)


def _is_student_viewer(db: Session, user: User, student_id: uuid.UUID) -> bool:
    if user.role == UserRole.ADMIN:
        return False
    return get_access_level(db, user, student_id) == AccessLevel.SELF


# --------------------------------------------------------------------------- recurring mistakes


def game_findings(db: Session, user: User, game_id: uuid.UUID, *, limit: int = 10) -> dict:
    """Findings per move of one game, each linked to the SAME mistake in the student's other
    games ("you did this before").

    Same mistake = same skill and subskill AND the same motif kind (missing your own mate is
    not the same mistake as allowing the opponent's). Unexplained errors are never matched,
    rejected findings never count.
    """
    game = db.get(Game, game_id)
    if game is None:
        raise NotFoundError("Game not found")
    require_student_access(db, user, game.student_id)
    student_viewer = _is_student_viewer(db, user, game.student_id)

    rows = db.execute(
        select(WeaknessObservation, MoveAnalysis, Game)
        .join(MoveAnalysis, MoveAnalysis.id == WeaknessObservation.move_analysis_id)
        .join(Game, Game.id == WeaknessObservation.game_id)
        .where(
            WeaknessObservation.student_id == game.student_id,
            WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
            WeaknessObservation.review_status != ReviewStatus.REJECTED,
        )
    ).all()

    def key(o: WeaknessObservation):
        return (o.skill_code, o.subskill_code, o.details.get("motif_kind"))

    def when(g: Game):
        return (g.played_at is None, g.played_at or date.max, g.created_at)

    by_key: dict[tuple, dict] = {}
    for o, m, g in rows:
        if o.skill_code == UNCLASSIFIED:
            continue
        # One entry per (game, ply) per mistake type.
        by_key.setdefault(key(o), {}).setdefault((g.id, m.ply), (o, m, g))

    findings = []
    for o, m, g in rows:
        if g.id != game.id:
            continue
        others = (
            []
            if o.skill_code == UNCLASSIFIED
            else [v for (gid, _), v in by_key.get(key(o), {}).items() if gid != game.id]
        )
        others.sort(key=lambda v: (when(v[2]), v[1].ply))
        findings.append(
            {
                "observation_id": str(o.id),
                "ply": m.ply,
                "move_number": (m.ply + 1) // 2,
                "san_move": m.san_move,
                "skill_code": o.skill_code,
                "subskill_code": o.subskill_code,
                "evidence_type": o.evidence_type.value,
                "motif_kind": o.details.get("motif_kind"),
                "severity": o.severity,
                "review_status": o.review_status.value,
                "same_mistake_count": len(others),
                "same_mistake_elsewhere": [
                    {
                        "game_id": str(og.id),
                        "ply": om.ply,
                        "move_number": (om.ply + 1) // 2,
                        "san_move": om.san_move,
                        "played_at": og.played_at.isoformat() if og.played_at else None,
                        "opponent": og.black_name
                        if og.student_color and og.student_color.value == "white"
                        else og.white_name,
                        "earlier": when(og) < when(game),
                        "review_status": oo.review_status.value,
                    }
                    for oo, om, og in others[:limit]
                ],
            }
        )
    findings.sort(key=lambda f: (f["ply"], f["skill_code"]))
    return {"game_id": str(game.id), "student_view": student_viewer, "findings": findings}
