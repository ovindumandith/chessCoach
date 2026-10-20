"""Analysis worker: `python -m chesscoach.analysis.worker`.

Polls the `analysis_runs` table, claims one job at a time, and runs Stockfish on it.
- Claiming uses SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL, so several workers never
  take the same job. (SQLite ignores the lock; use one worker there.)
- Retries are safe: a run's move analyses are replaced, never duplicated (unique run+ply).
- Jobs left `running` by a crashed worker are reclaimed after `worker_stale_after_seconds`.
- Concurrency is bounded by the number of worker processes (one engine each).
"""

import logging
import os
import signal
import socket
import time
import uuid
from datetime import timedelta

import chess.engine
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from chesscoach.analysis.engine import EngineConfig, PositionAnalyzer, StockfishAnalyzer
from chesscoach.analysis.game_analyzer import AnalysisSettings, MoveRecord, analyze_game, versions
from chesscoach.core.config import Settings, get_settings
from chesscoach.db.enums import AnalysisPass, JobStatus, MappingStatus
from chesscoach.db.models import AnalysisRun, Game, MoveAnalysis
from chesscoach.db.session import get_sessionmaker
from chesscoach.db.types import utcnow

log = logging.getLogger("chesscoach.worker")


def worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def claim_next_run(db: Session, settings: Settings, claimant: str) -> AnalysisRun | None:
    while True:
        stale_before = utcnow() - timedelta(seconds=settings.worker_stale_after_seconds)
        run = db.scalars(
            select(AnalysisRun)
            .where(
                or_(
                    AnalysisRun.status == JobStatus.QUEUED,
                    and_(
                        AnalysisRun.status == JobStatus.RUNNING,
                        AnalysisRun.started_at < stale_before,
                    ),
                )
            )
            .order_by(AnalysisRun.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if run is None:
            db.rollback()
            return None
        if run.status == JobStatus.RUNNING and run.attempts >= settings.analysis_max_attempts:
            run.status = JobStatus.FAILED
            run.error_message = "Abandoned by worker and retry limit reached"
            db.commit()
            continue
        run.status = JobStatus.RUNNING
        run.attempts += 1
        run.claimed_by = claimant
        run.started_at = utcnow()
        db.commit()
        return run


def engine_config(settings: Settings) -> EngineConfig:
    return EngineConfig(
        path=settings.stockfish_path,
        depth=settings.stockfish_depth,
        threads=settings.stockfish_threads,
        hash_mb=settings.stockfish_hash_mb,
        multipv=settings.analysis_multipv,
    )


def process_run(
    db: Session, run: AnalysisRun, analyzer: PositionAnalyzer, settings: Settings
) -> None:
    game = db.get(Game, run.game_id)
    if game is None:
        raise ValueError("Game no longer exists")
    if game.student_color is None or game.mapping_status not in (
        MappingStatus.MAPPED,
        MappingStatus.CONFIRMED,
    ):
        raise ValueError("Game mapping is not resolved")

    if run.pass_type == AnalysisPass.CRITICAL:
        only_plies = set(run.configuration.get("plies", []))
        depth = int(run.configuration.get("depth", settings.stockfish_critical_depth))
    else:
        only_plies = None
        depth = settings.stockfish_depth

    analysis_settings = AnalysisSettings(
        depth=depth,
        multipv=settings.analysis_multipv,
        critical_wp_loss=settings.analysis_critical_wp_loss,
    )
    records = analyze_game(
        game.raw_pgn,
        game.student_color,
        analyzer,
        analysis_settings,
        game_key=run.id,
        only_plies=only_plies,
    )

    # Idempotent retry: replace whatever a previous failed attempt may have written.
    db.execute(delete(MoveAnalysis).where(MoveAnalysis.analysis_run_id == run.id))
    db.add_all(_to_row(run.id, r) for r in records)

    identity = analyzer.identity
    run.engine_name = identity.name
    run.engine_version = identity.version
    run.engine_checksum = identity.checksum
    run.configuration = {
        **run.configuration,
        **versions(),
        "depth": depth,
        "multipv": settings.analysis_multipv,
        "critical_wp_loss": settings.analysis_critical_wp_loss,
        "engine_options": identity.options,
        "student_color": game.student_color.value,
        "moves_analyzed": len(records),
    }
    run.status = JobStatus.COMPLETED
    run.completed_at = utcnow()
    run.error_message = None

    if run.pass_type == AnalysisPass.BASELINE and settings.analysis_critical_enabled:
        critical_plies = [r.ply for r in records if r.critical]
        if critical_plies:
            db.add(
                AnalysisRun(
                    game_id=game.id,
                    pass_type=AnalysisPass.CRITICAL,
                    analysis_version=run.analysis_version,
                    status=JobStatus.QUEUED,
                    requested_by=run.requested_by,
                    configuration={
                        "parent_run_id": str(run.id),
                        "plies": critical_plies,
                        "depth": settings.stockfish_critical_depth,
                    },
                )
            )
    db.commit()


def mark_failure(db: Session, run_id: uuid.UUID, exc: BaseException, settings: Settings) -> None:
    db.rollback()
    run = db.get(AnalysisRun, run_id)
    if run is None:
        return
    # Error text only: never include PGN content or personal data.
    run.error_message = f"{type(exc).__name__}: {exc}"[:1000]
    run.status = (
        JobStatus.QUEUED if run.attempts < settings.analysis_max_attempts else JobStatus.FAILED
    )
    db.commit()


def run_once(db: Session, analyzer: PositionAnalyzer, settings: Settings, claimant: str) -> bool:
    """Claim and process a single job. Returns False if the queue was empty."""
    run = claim_next_run(db, settings, claimant)
    if run is None:
        return False
    log.info("Processing analysis run %s (%s, attempt %d)", run.id, run.pass_type, run.attempts)
    try:
        process_run(db, run, analyzer, settings)
        log.info("Completed analysis run %s", run.id)
    except chess.engine.EngineTerminatedError:
        mark_failure(db, run.id, RuntimeError("Engine process terminated"), settings)
        raise  # caller restarts the engine
    except Exception as exc:
        log.exception("Analysis run %s failed", run.id)
        mark_failure(db, run.id, exc, settings)
    return True


def _to_row(run_id: uuid.UUID, r: MoveRecord) -> MoveAnalysis:
    features = {
        **r.features,
        "critical": r.critical,
        "mate_transition": r.transition.value,
    }
    if r.second_best is not None:
        features["second_best_mate"] = r.second_best.mate
    return MoveAnalysis(
        analysis_run_id=run_id,
        ply=r.ply,
        fen_before=r.fen_before,
        fen_after=r.fen_after,
        uci_move=r.uci_move,
        san_move=r.san_move,
        student_move=True,
        phase=r.phase,
        eval_before_cp=r.eval_before.cp,
        eval_after_cp=r.eval_after.cp,
        eval_before_mate=r.eval_before.mate,
        eval_after_mate=r.eval_after.mate,
        best_move_uci=r.best_move_uci,
        second_best_cp=r.second_best.cp if r.second_best else None,
        principal_variation=r.principal_variation,
        best_move_loss_cp=r.cp_loss,
        win_prob_loss=r.win_prob_loss,
        search_depth=r.search_depth,
        clock_before_ms=r.clock_before_ms,
        clock_after_ms=r.clock_after_ms,
        features=features,
    )


def run_forever(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(message)s")
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True
        log.info("Shutdown requested; finishing current job")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    claimant = worker_id()
    session_factory = get_sessionmaker()
    config = engine_config(settings)
    while not stop:
        try:
            with StockfishAnalyzer(config) as analyzer:
                log.info(
                    "Worker %s started with %s %s",
                    claimant,
                    analyzer.identity.name,
                    analyzer.identity.version,
                )
                while not stop:
                    with session_factory() as db:
                        busy = run_once(db, analyzer, settings, claimant)
                    if not busy:
                        time.sleep(settings.worker_poll_seconds)
        except chess.engine.EngineTerminatedError:
            log.warning("Engine terminated; restarting")
            time.sleep(1)
        except FileNotFoundError:
            log.exception("Stockfish binary missing; retrying in 30s")
            time.sleep(30)


if __name__ == "__main__":
    run_forever()
