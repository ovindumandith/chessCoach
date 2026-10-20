import uuid

from fastapi import APIRouter, Response, status

from chesscoach.analysis import service
from chesscoach.annotation import service as annotation_service
from chesscoach.api.deps import CurrentUser, DbSession, rate_limited
from chesscoach.api.schemas import AnalysisJobOut, AnalyzeRequest, GameAnalysisOut, MoveAnalysisOut

router = APIRouter(tags=["analysis"])


@router.post(
    "/games/{game_id}/analyze",
    response_model=AnalysisJobOut,
    dependencies=[rate_limited("analysis", lambda s: s.rate_limit_analysis_per_hour)],
)
def analyze_game(
    game_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    response: Response,
    body: AnalyzeRequest | None = None,
) -> AnalysisJobOut:
    """Queue Stockfish analysis. Returns 202 for a new job, 200 if an existing job is reused."""
    result = service.queue_game_analysis(db, user, game_id, force=bool(body and body.force))
    response.status_code = status.HTTP_202_ACCEPTED if result.created else status.HTTP_200_OK
    return AnalysisJobOut.model_validate(result.run)


@router.get("/analysis-jobs/{job_id}", response_model=AnalysisJobOut)
def get_analysis_job(job_id: uuid.UUID, db: DbSession, user: CurrentUser) -> AnalysisJobOut:
    return AnalysisJobOut.model_validate(service.get_job(db, user, job_id))


@router.get("/games/{game_id}/analysis", response_model=GameAnalysisOut)
def get_game_analysis(game_id: uuid.UUID, db: DbSession, user: CurrentUser) -> GameAnalysisOut:
    result = service.get_game_analysis(db, user, game_id)
    return GameAnalysisOut(
        game_id=result.game.id,
        student_color=result.game.student_color,
        baseline=AnalysisJobOut.model_validate(result.baseline),
        moves=[MoveAnalysisOut.model_validate(m) for m in result.moves],
        critical=AnalysisJobOut.model_validate(result.critical) if result.critical else None,
        critical_moves=[MoveAnalysisOut.model_validate(m) for m in result.critical_moves],
    )


@router.get("/games/{game_id}/analysis-status")
def get_analysis_status(game_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    """queued / running / deepening / analyzed / failed / not_requested, with queue position."""
    return service.analysis_status(db, user, game_id)


@router.get("/games/{game_id}/annotations")
def get_annotations(game_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    """Every move of both sides graded, with plain-language reasons (+ = White better)."""
    return annotation_service.game_annotations(db, user, game_id)
