"""Analysis job queueing and read-side queries. No engine work happens here."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.analysis.game_analyzer import ANALYSIS_VERSION
from chesscoach.core.access import require_student_access
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
    require_student_access(db, user, game.student_id, coach_only=True)
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
