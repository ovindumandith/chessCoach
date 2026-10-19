import uuid

from fastapi import APIRouter

from chesscoach.api.deps import CurrentUser, DbSession
from chesscoach.api.schemas import GameDetail, MappingConfirm
from chesscoach.core.access import require_student_access
from chesscoach.core.errors import NotFoundError
from chesscoach.db.models import Game
from chesscoach.ingestion.service import confirm_game_mapping

router = APIRouter(prefix="/games", tags=["games"])


@router.get("/{game_id}", response_model=GameDetail)
def get_game(game_id: uuid.UUID, db: DbSession, user: CurrentUser) -> GameDetail:
    game = db.get(Game, game_id)
    if game is None:
        raise NotFoundError("Game not found")
    require_student_access(db, user, game.student_id)
    return GameDetail.model_validate(game)


@router.patch("/{game_id}/mapping", response_model=GameDetail)
def confirm_mapping(
    game_id: uuid.UUID, body: MappingConfirm, db: DbSession, user: CurrentUser
) -> GameDetail:
    return GameDetail.model_validate(confirm_game_mapping(db, user, game_id, body.student_color))
