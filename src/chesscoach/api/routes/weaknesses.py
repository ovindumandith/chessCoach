import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query

from chesscoach.api.deps import CurrentUser, DbSession
from chesscoach.api.schemas import ClassifyResultOut, Page, ReviewRequest, WeaknessOut
from chesscoach.classification import service
from chesscoach.classification.taxonomy import get_taxonomy
from chesscoach.db.enums import EvidenceType, ReviewStatus

router = APIRouter(tags=["weaknesses"])


@router.get("/taxonomy")
def get_skill_taxonomy(user: CurrentUser) -> dict:
    """The versioned skill taxonomy, for review UIs and correction dropdowns."""
    return get_taxonomy().model_dump()


@router.post("/games/{game_id}/classify", response_model=ClassifyResultOut)
def classify_game(game_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ClassifyResultOut:
    """Re-derive candidate observations from stored analysis. Reviewed findings are kept."""
    return ClassifyResultOut(**asdict(service.classify_game(db, game_id, actor=user)))


@router.get("/students/{student_id}/weaknesses", response_model=Page[WeaknessOut])
def list_weaknesses(
    student_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    skill_code: str | None = None,
    evidence_type: EvidenceType | None = None,
    review_status: ReviewStatus | None = None,
) -> Page[WeaknessOut]:
    rows, total = service.list_weaknesses(
        db,
        user,
        student_id,
        limit=limit,
        offset=offset,
        skill_code=skill_code,
        evidence_type=evidence_type,
        review_status=review_status,
    )
    return Page(
        items=[WeaknessOut.from_view(v) for v in rows], total=total, limit=limit, offset=offset
    )


@router.patch("/observations/{observation_id}/review", response_model=WeaknessOut)
def review_observation(
    observation_id: uuid.UUID, body: ReviewRequest, db: DbSession, user: CurrentUser
) -> WeaknessOut:
    obs = service.review_observation(
        db,
        user,
        observation_id,
        action=body.action,
        skill_code=body.skill_code,
        subskill_code=body.subskill_code,
        note=body.note,
    )
    return WeaknessOut.from_view(service.get_observation_view(db, obs.id))


@router.get("/games/{game_id}/findings")
def game_findings(game_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    """Findings per move, each linked to the same mistake in the student's other games."""
    return service.game_findings(db, user, game_id)
