"""Analysis job queueing and read-side queries. No engine work happens here."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chesscoach.analysis.game_analyzer import ANALYSIS_VERSION
from chesscoach.core.access import require_admin, require_own_student_record, require_student_access
from chesscoach.core.audit import record_audit
from chesscoach.core.errors import ConflictError, NotFoundError
from chesscoach.db.enums import AnalysisPass, JobStatus, MappingStatus
from chesscoach.db.models import AnalysisRun, Game, MoveAnalysis, User

RESOLVED = (MappingStatus.MAPPED, MappingStatus.CONFIRMED)
ACTIVE = (JobStatus.QUEUED, JobStatus.RUNNING)


@dataclass
class QueueResult:
    run: AnalysisRun
    created: bool


def _get_game(db: Session, game_id: uuid.UUID) -> Game:
    game = db.get(Game, game_id)
    if game is None:
        raise NotFoundError("Game not found")
    return game


def queue_game_analysis(
    db: Session, user: User, game_id: uuid.UUID, *, force: bool = False
) -> QueueResult:
    game = _get_game(db, game_id)
    # Students queue their own games. Forcing a re-run of a finished analysis (extra engine
    # time, new analysis rows) is an operator action.
    require_own_student_record(db, user, game.student_id, allow_admin=True)
    if force:
        require_admin(user)
    if game.mapping_status not in RESOLVED or game.student_color is None:
        raise ConflictError(
            "The student's color in this game must be confirmed before analysis",
            details={"mapping_status": game.mapping_status.value},
        )

    existing = db.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.game_id == game.id, AnalysisRun.pass_type == AnalysisPass.BASELINE)
        .order_by(AnalysisRun.created_at.desc())
    ).all()
    for run in existing:
        if run.status in ACTIVE:
            return QueueResult(run, created=False)
    if not force:
        for run in existing:
            if run.status == JobStatus.COMPLETED and run.analysis_version == ANALYSIS_VERSION:
                return QueueResult(run, created=False)

    run = AnalysisRun(
        game_id=game.id,
        pass_type=AnalysisPass.BASELINE,
        analysis_version=ANALYSIS_VERSION,
        status=JobStatus.QUEUED,
        requested_by=user.id,
    )
    db.add(run)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        action="analysis.queue",
        entity_type="analysis_run",
        entity_id=run.id,
        details={"game_id": str(game.id), "force": force},
    )
    db.commit()
    return QueueResult(run, created=True)


def get_job(db: Session, user: User, run_id: uuid.UUID) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise NotFoundError("Analysis job not found")
    require_student_access(db, user, _get_game(db, run.game_id).student_id)
    return run


@dataclass
class GameAnalysis:
    game: Game
    baseline: AnalysisRun
    moves: list[MoveAnalysis]
    critical: AnalysisRun | None
    critical_moves: list[MoveAnalysis]


def get_game_analysis(db: Session, user: User, game_id: uuid.UUID) -> GameAnalysis:
    game = _get_game(db, game_id)
    require_student_access(db, user, game.student_id)

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
        latest = db.scalars(
            select(AnalysisRun)
            .where(AnalysisRun.game_id == game.id)
            .order_by(AnalysisRun.created_at.desc())
            .limit(1)
        ).first()
        raise NotFoundError(
            "No completed analysis for this game",
            details={
                "latest_job_status": latest.status.value if latest else None,
                "latest_job_id": str(latest.id) if latest else None,
            },
        )

    critical = next(
        (
            run
            for run in db.scalars(
                select(AnalysisRun)
                .where(
                    AnalysisRun.game_id == game.id,
                    AnalysisRun.pass_type == AnalysisPass.CRITICAL,
                    AnalysisRun.status == JobStatus.COMPLETED,
                )
                .order_by(AnalysisRun.completed_at.desc())
            )
            if run.configuration.get("parent_run_id") == str(baseline.id)
        ),
        None,
    )
    return GameAnalysis(
        game=game,
        baseline=baseline,
        moves=_moves(db, baseline.id),
        critical=critical,
        critical_moves=_moves(db, critical.id) if critical else [],
    )


def _moves(db: Session, run_id: uuid.UUID) -> list[MoveAnalysis]:
    return list(
        db.scalars(
            select(MoveAnalysis)
            .where(MoveAnalysis.analysis_run_id == run_id)
            .order_by(MoveAnalysis.ply)
        ).all()
    )


# --------------------------------------------------------------------------- status


def _states(db: Session, game_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Analysis state per game from its latest baseline run and that run's critical pass.

    not_requested | queued | running | deepening (results ready, deeper pass still running)
    | analyzed | failed
    """
    runs = db.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.game_id.in_(game_ids))
        .order_by(AnalysisRun.created_at)
    ).all()
    baseline: dict[uuid.UUID, AnalysisRun] = {}
    critical: dict[str, AnalysisRun] = {}
    for run in runs:
        if run.pass_type == AnalysisPass.BASELINE:
            baseline[run.game_id] = run  # latest wins (ordered by created_at)
        else:
            critical[run.configuration.get("parent_run_id", "")] = run
    out = {}
    for gid in game_ids:
        b = baseline.get(gid)
        c = critical.get(str(b.id)) if b else None
        if b is None:
            state = "not_requested"
        elif b.status == JobStatus.COMPLETED:
            state = "deepening" if c is not None and c.status in ACTIVE else "analyzed"
        else:
            state = b.status.value  # queued | running | failed
        out[gid] = {"state": state, "baseline": b, "critical": c}
    return out


def analysis_states(db: Session, game_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return {gid: s["state"] for gid, s in _states(db, game_ids).items()} if game_ids else {}


def analysis_status(db: Session, user: User, game_id: uuid.UUID) -> dict:
    """Status of a game's analysis, so clients can wait without polling for a 404."""
    game = _get_game(db, game_id)
    require_student_access(db, user, game.student_id)
    s = _states(db, [game.id])[game.id]
    b, c = s["baseline"], s["critical"]
    ahead = None
    if b is not None and b.status == JobStatus.QUEUED:
        ahead = db.scalar(
            select(func.count())
            .select_from(AnalysisRun)
            .where(AnalysisRun.status.in_(ACTIVE), AnalysisRun.created_at < b.created_at)
        )
    return {
        "game_id": str(game.id),
        "state": s["state"],
        "results_available": s["state"] in ("analyzed", "deepening"),
        "jobs_ahead": ahead,
        "baseline_job_id": str(b.id) if b else None,
        "critical_job_id": str(c.id) if c else None,
        "error_message": b.error_message
        if b is not None and b.status == JobStatus.FAILED
        else None,
        "moves_to_analyze": (game.ply_count + 1) // 2
        if game.student_color and game.student_color.value == "white"
        else game.ply_count // 2,
    }
