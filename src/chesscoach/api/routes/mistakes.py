import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from chesscoach import mistakes
from chesscoach.api.deps import CurrentUser, DbSession

router = APIRouter(tags=["mistakes"])
Limit = Annotated[int, Query(ge=1, le=50)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/students/{student_id}/mistakes")
def list_mistakes(
    student_id: uuid.UUID, db: DbSession, user: CurrentUser, limit: Limit = 10, offset: Offset = 0
) -> dict:
    """The student's mistakes grouped by game (newest first), with acknowledgements."""
    return mistakes.student_mistakes(db, user, student_id, limit=limit, offset=offset)


@router.put("/games/{game_id}/mistakes/{ply}/acknowledgement")
def acknowledge_mistake(game_id: uuid.UUID, ply: int, db: DbSession, user: CurrentUser) -> dict:
    """The student acknowledges their mistake on this move (idempotent)."""
    ack = mistakes.acknowledge(db, user, game_id, ply)
    return {"game_id": str(game_id), "ply": ply, "acknowledged_at": ack.acknowledged_at}


@router.delete(
    "/games/{game_id}/mistakes/{ply}/acknowledgement", status_code=status.HTTP_204_NO_CONTENT
)
def unacknowledge_mistake(
    game_id: uuid.UUID, ply: int, db: DbSession, user: CurrentUser
) -> Response:
    mistakes.unacknowledge(db, user, game_id, ply)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
