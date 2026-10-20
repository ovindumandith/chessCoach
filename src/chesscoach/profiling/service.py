"""Build, persist and read versioned student profiles from stored, classified evidence.

Engine analysis is never redone here. Aggregation re-reads stored observations, which is
cheap at pilot scale (about 50 games per student). A new snapshot is written only when
the evidence fingerprint changes, so repeated rebuilds do not create spurious versions.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chesscoach.analysis.scores import Evaluation, win_probability
from chesscoach.classification.classifier import (
    CLASSIFIER_VERSION,
    endgame_type,
    is_time_trouble,
    parse_base_time,
)
from chesscoach.classification.service import latest_evidence
from chesscoach.classification.taxonomy import get_taxonomy
from chesscoach.core.access import require_student_access
from chesscoach.core.audit import record_audit
from chesscoach.core.errors import ConflictError, NotFoundError
from chesscoach.db.enums import MappingStatus
from chesscoach.db.models import (
    Game,
    MoveAnalysis,
    ProfileSnapshot,
    SkillOpportunity,
    StudentSkillProfile,
    User,
    WeaknessObservation,
)
from chesscoach.profiling.aggregator import (
    SETTINGS,
    MoveFact,
    ObsFact,
    OppFact,
    build_profile,
    previous_index,
)

RESOLVED = (MappingStatus.MAPPED, MappingStatus.CONFIRMED)


@dataclass
class Facts:
    moves: list[MoveFact]
    observations: list[ObsFact]
    opportunities: list[OppFact]
    games_included: int
    fingerprint: str


def gather_facts(db: Session, student_id: uuid.UUID, *, cutoff: date | None = None) -> Facts:
    """Collect evidence for a student's analyzed games, oldest game first.

    With `cutoff`, only games played strictly before that date are used, so a profile can
    be built without seeing the games it is later evaluated against. Games without a date
    are excluded from cutoff builds, because their position in time is unknown.
    """
    query = select(Game).where(Game.student_id == student_id, Game.mapping_status.in_(RESOLVED))
    if cutoff is not None:
        query = query.where(Game.played_at.is_not(None), Game.played_at < cutoff)
    games = sorted(
        db.scalars(query).all(),
        key=lambda g: (g.played_at or date.max, g.created_at, str(g.id)),
    )

    moves: list[MoveFact] = []
    fp_parts: list = [SETTINGS["profile_version"], CLASSIFIER_VERSION, str(cutoff)]
    order: dict[uuid.UUID, int] = {}
    analyzed: list[Game] = []
    for game in games:
        try:
            _, _, rows = latest_evidence(db, game)
        except ConflictError:
            continue  # not analyzed yet
        order[game.id] = len(analyzed)
        analyzed.append(game)
        base = parse_base_time(game.time_control)
        for m in rows:
            moves.append(_move_fact(m, game, order[game.id], base))
        fp_parts.append([str(game.id), sorted(str(m.id) for m in rows)])

    game_ids = list(order)
    obs_rows = (
        db.execute(
            select(WeaknessObservation, MoveAnalysis.phase)
            .join(MoveAnalysis, MoveAnalysis.id == WeaknessObservation.move_analysis_id)
            .where(
                WeaknessObservation.game_id.in_(game_ids),
                WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
            )
        ).all()
        if game_ids
        else []
    )
    observations = []
    for o, phase in obs_rows:
        original = o.details.get("original")
        observations.append(
            ObsFact(
                id=str(o.id),
                game_id=str(o.game_id),
                move_analysis_id=str(o.move_analysis_id),
                game_order=order[o.game_id],
                phase=phase.value,
                skill_code=o.skill_code,
                subskill_code=o.subskill_code,
                evidence_type=o.evidence_type.value,
                motif_kind=o.details.get("motif_kind"),
                severity=o.severity or 0.0,
                review_status=o.review_status.value,
                original_key=(original["skill_code"], original["subskill_code"])
                if original
                else None,
            )
        )
        fp_parts.append([str(o.id), o.review_status.value, o.skill_code, o.subskill_code])

    opp_rows = (
        db.scalars(
            select(SkillOpportunity).where(
                SkillOpportunity.game_id.in_(game_ids),
                SkillOpportunity.classifier_version == CLASSIFIER_VERSION,
            )
        ).all()
        if game_ids
        else []
    )
    opportunities = [
        OppFact(
            str(o.game_id), str(o.move_analysis_id), o.skill_code, o.subskill_code, o.outcome.value
        )
        for o in opp_rows
    ]
    fp_parts += sorted([str(o.id), o.outcome.value] for o in opp_rows)

    fingerprint = hashlib.sha256(
        json.dumps(fp_parts, sort_keys=True, default=str).encode()
    ).hexdigest()
    return Facts(moves, observations, opportunities, len(analyzed), fingerprint)


@dataclass
class RebuildResult:
    snapshot: ProfileSnapshot
    created: bool


def rebuild_profile(
    db: Session,
    student_id: uuid.UUID,
    *,
    triggered_by: str,
    actor: User | None = None,
    cutoff: date | None = None,
) -> RebuildResult:
    if actor is not None:
        require_student_access(db, actor, student_id, coach_only=True)
    facts = gather_facts(db, student_id, cutoff=cutoff)
    latest = _latest_snapshot(db, student_id, cutoff=cutoff)
    if latest is not None and latest.fingerprint == facts.fingerprint:
        return RebuildResult(latest, created=False)

    taxonomy = get_taxonomy()
    previous = previous_index(latest.skills, latest.profile_version) if latest else None
    result = build_profile(
        taxonomy,
        facts.moves,
        facts.observations,
        facts.opportunities,
        games_included=facts.games_included,
        previous=previous,
    )
    version = (
        db.scalar(
            select(func.max(ProfileSnapshot.profile_version)).where(
                ProfileSnapshot.student_id == student_id
            )
        )
        or 0
    ) + 1
    snapshot = ProfileSnapshot(
        student_id=student_id,
        profile_version=version,
        fingerprint=facts.fingerprint,
        cutoff_date=cutoff,
        settings={
            **SETTINGS,
            "classifier_version": CLASSIFIER_VERSION,
            "taxonomy_version": taxonomy.version,
        },
        summary=result.summary,
        triggered_by=triggered_by,
    )
    db.add(snapshot)
    db.flush()
    for s in result.skills:
        snapshot.skills.append(
            StudentSkillProfile(
                student_id=student_id,
                skill_code=s.skill_code,
                subskill_code=s.subskill_code,
                profile_version=version,
                state=s.state,
                error_rate=s.error_rate,
                opportunity_count=s.opportunity_count,
                error_count=s.error_count,
                games_affected=s.games_affected,
                confidence=s.confidence,
                priority_score=s.priority,
                evidence_summary=s.summary,
            )
        )
    if actor is not None:
        record_audit(
            db,
            actor_user_id=actor.id,
            action="profile.rebuild",
            entity_type="profile_snapshot",
            entity_id=snapshot.id,
            details={"profile_version": version, "cutoff": str(cutoff) if cutoff else None},
        )
    db.commit()
    db.refresh(snapshot)
    return RebuildResult(snapshot, created=True)


@dataclass
class ProfileView:
    snapshot: ProfileSnapshot
    stale: bool


def get_profile(db: Session, user: User, student_id: uuid.UUID) -> ProfileView:
    require_student_access(db, user, student_id)
    snapshot = _latest_snapshot(db, student_id, cutoff=None)
    if snapshot is None:
        raise NotFoundError("No profile has been built for this student yet")
    stale = gather_facts(db, student_id).fingerprint != snapshot.fingerprint
    return ProfileView(snapshot, stale)


def list_snapshots(
    db: Session, user: User, student_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[ProfileSnapshot], int]:
    require_student_access(db, user, student_id)
    query = select(ProfileSnapshot).where(ProfileSnapshot.student_id == student_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(ProfileSnapshot.profile_version.desc()).limit(limit).offset(offset)
    ).all()
    return list(rows), total


def _latest_snapshot(
    db: Session, student_id: uuid.UUID, *, cutoff: date | None
) -> ProfileSnapshot | None:
    query = select(ProfileSnapshot).where(ProfileSnapshot.student_id == student_id)
    query = query.where(
        ProfileSnapshot.cutoff_date.is_(None)
        if cutoff is None
        else ProfileSnapshot.cutoff_date == cutoff
    )
    return db.scalars(query.order_by(ProfileSnapshot.profile_version.desc()).limit(1)).first()


def _move_fact(m: MoveAnalysis, game: Game, game_order: int, base_time: int | None) -> MoveFact:
    eval_before = (
        Evaluation(mate=m.eval_before_mate)
        if m.eval_before_mate is not None
        else Evaluation(cp=m.eval_before_cp)
    )
    features = m.features or {}
    return MoveFact(
        game_id=str(game.id),
        move_analysis_id=str(m.id),
        game_order=game_order,
        phase=m.phase.value,
        wp_before=win_probability(eval_before),
        only_move_gap=features.get("only_move_gap_wp"),
        forced=features.get("legal_moves") == 1,
        time_trouble=is_time_trouble(m.clock_before_ms, base_time),
        endgame_type=endgame_type(m.fen_before) if m.phase.value == "endgame" else None,
    )
