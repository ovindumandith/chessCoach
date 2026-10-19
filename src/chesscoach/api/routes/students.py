import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query, UploadFile, status

from chesscoach import students as student_service
from chesscoach.api.deps import CurrentUser, DbSession
from chesscoach.api.schemas import (
    AliasCreate,
    GameSummary,
    ImportReportOut,
    Page,
    StudentCreate,
    StudentOut,
)
from chesscoach.core.access import require_student_access
from chesscoach.core.config import get_settings
from chesscoach.core.errors import PayloadTooLargeError
from chesscoach.ingestion import queries as game_queries
from chesscoach.ingestion.service import import_pgn
from chesscoach.ingestion.storage import LocalFileStorage

router = APIRouter(prefix="/students", tags=["students"])

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


@router.post("", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def create_student(body: StudentCreate, db: DbSession, user: CurrentUser) -> StudentOut:
    student = student_service.create_student(db, user, **body.model_dump())
    return StudentOut.from_model(student)


@router.get("", response_model=Page[StudentOut])
def list_students(
    db: DbSession, user: CurrentUser, limit: Limit = 50, offset: Offset = 0
) -> Page[StudentOut]:
    rows, total = student_service.list_students(db, user, limit=limit, offset=offset)
    return Page(
        items=[StudentOut.from_model(s) for s in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{student_id}", response_model=StudentOut)
def get_student(student_id: uuid.UUID, db: DbSession, user: CurrentUser) -> StudentOut:
    return StudentOut.from_model(require_student_access(db, user, student_id))


@router.post(
    "/{student_id}/aliases", response_model=StudentOut, status_code=status.HTTP_201_CREATED
)
def add_alias(
    student_id: uuid.UUID, body: AliasCreate, db: DbSession, user: CurrentUser
) -> StudentOut:
    return StudentOut.from_model(student_service.add_alias(db, user, student_id, body.alias))


@router.post(
    "/{student_id}/games/import",
    response_model=ImportReportOut,
    status_code=status.HTTP_201_CREATED,
)
async def import_games(
    student_id: uuid.UUID, file: UploadFile, db: DbSession, user: CurrentUser
) -> ImportReportOut:
    settings = get_settings()
    max_bytes = settings.pgn_max_upload_bytes
    # Read at most one byte past the limit so oversized uploads are never fully buffered.
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise PayloadTooLargeError(f"File exceeds the {settings.pgn_max_upload_mb} MB upload limit")
    report = import_pgn(
        db,
        LocalFileStorage(settings.storage_dir),
        user,
        student_id,
        filename=file.filename or "upload.pgn",
        data=data,
        max_bytes=max_bytes,
    )
    return ImportReportOut(**asdict(report))


@router.get("/{student_id}/games", response_model=Page[GameSummary])
def list_games(
    student_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: Limit = 50,
    offset: Offset = 0,
    needs_mapping: bool | None = None,
) -> Page[GameSummary]:
    require_student_access(db, user, student_id)
    rows, total = game_queries.list_student_games(
        db, student_id, limit=limit, offset=offset, needs_mapping=needs_mapping
    )
    return Page(
        items=[GameSummary.model_validate(g) for g in rows], total=total, limit=limit, offset=offset
    )
