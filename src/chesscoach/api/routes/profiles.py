import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from chesscoach.api.deps import CurrentUser, DbSession
from chesscoach.api.schemas import (
    Page,
    ProfileOut,
    ProfileSnapshotOut,
    RebuildRequest,
    SkillProfileOut,
)
from chesscoach.profiling import service

router = APIRouter(prefix="/students/{student_id}/profile", tags=["profiles"])


def _out(snapshot, stale: bool) -> ProfileOut:
    return ProfileOut(
        snapshot=ProfileSnapshotOut.model_validate(snapshot),
        stale=stale,
        skills=[SkillProfileOut.model_validate(s) for s in snapshot.skills],
    )


@router.get("", response_model=ProfileOut)
def get_profile(student_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ProfileOut:
    """Latest profile, skills ordered by training priority."""
    view = service.get_profile(db, user, student_id)
    return _out(view.snapshot, view.stale)


@router.post("/rebuild", response_model=ProfileOut)
def rebuild_profile(
    student_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    response: Response,
    body: RebuildRequest | None = None,
) -> ProfileOut:
    """Build a new snapshot if the evidence changed (201), else return the latest (200)."""
    result = service.rebuild_profile(
        db,
        student_id,
        triggered_by="coach",
        actor=user,
        cutoff=body.cutoff_date if body else None,
    )
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return _out(result.snapshot, stale=False)


@router.get("/history", response_model=Page[ProfileSnapshotOut])
def profile_history(
    student_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProfileSnapshotOut]:
    rows, total = service.list_snapshots(db, user, student_id, limit=limit, offset=offset)
    return Page(
        items=[ProfileSnapshotOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
