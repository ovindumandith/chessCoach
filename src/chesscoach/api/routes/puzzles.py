import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from chesscoach.api.deps import CurrentUser, DbSession, rate_limited
from chesscoach.puzzles import service

router = APIRouter(tags=["puzzles"])
creating = rate_limited("exercises", lambda s: s.rate_limit_exercises_per_hour)


class SkillSetRequest(BaseModel):
    skill_code: str
    subskill_code: str | None = None


class MoveRequest(BaseModel):
    move: str = Field(min_length=4, max_length=5, description="UCI, e.g. e2e4 or e7e8q")


@router.post(
    "/games/{game_id}/mistakes/{ply}/puzzles",
    status_code=status.HTTP_201_CREATED,
    dependencies=[creating],
)
def puzzles_for_mistake(game_id: uuid.UUID, ply: int, db: DbSession, user: CurrentUser) -> dict:
    """A set of Lichess puzzles of this mistake's kind, getting harder (reuses an open set)."""
    return service.set_for_mistake(db, user, game_id, ply)


@router.post(
    "/students/{student_id}/puzzle-sets",
    status_code=status.HTTP_201_CREATED,
    dependencies=[creating],
)
def puzzles_for_skill(
    student_id: uuid.UUID, body: SkillSetRequest, db: DbSession, user: CurrentUser
) -> dict:
    return service.set_for_skill(db, user, student_id, body.skill_code, body.subskill_code)


@router.get("/students/{student_id}/puzzle-sets")
def list_puzzle_sets(student_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    return service.list_sets(db, user, student_id)


@router.get("/puzzle-sets/{set_id}")
def get_puzzle_set(set_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    return service.get_set(db, user, set_id)


@router.post("/puzzles/{assignment_id}/moves")
def play_puzzle_move(
    assignment_id: uuid.UUID, body: MoveRequest, db: DbSession, user: CurrentUser
) -> dict:
    return service.play_move(db, user, assignment_id, body.move)


@router.post("/puzzles/{assignment_id}/reveal")
def reveal_puzzle(assignment_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    return service.reveal(db, user, assignment_id)
