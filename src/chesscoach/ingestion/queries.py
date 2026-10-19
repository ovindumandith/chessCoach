"""Read-side queries for imported games. Callers are responsible for access checks."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chesscoach.db.enums import MappingStatus
from chesscoach.db.models import Game

RESOLVED_MAPPING = (MappingStatus.MAPPED, MappingStatus.CONFIRMED)


def list_student_games(
    db: Session,
    student_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
    needs_mapping: bool | None = None,
) -> tuple[list[Game], int]:
    query = select(Game).where(Game.student_id == student_id)
    if needs_mapping is True:
        query = query.where(Game.mapping_status.not_in(RESOLVED_MAPPING))
    elif needs_mapping is False:
        query = query.where(Game.mapping_status.in_(RESOLVED_MAPPING))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(Game.played_at.desc().nulls_last(), Game.created_at.desc(), Game.game_index)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total
