"""Read-only access to evaluation data. Never writes to the live tables."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.classification.classifier import CLASSIFIER_VERSION
from chesscoach.classification.service import latest_evidence
from chesscoach.core.errors import ConflictError
from chesscoach.db.enums import MappingStatus
from chesscoach.db.models import Game, MoveAnalysis, Student, WeaknessObservation


@dataclass
class EvalMove:
    student_id: str
    game: Game
    move: MoveAnalysis


def label_of(skill_code: str, subskill_code: str | None) -> str:
    return f"{skill_code}.{subskill_code}" if subskill_code else skill_code


def student_ids(db: Session, selected: list[str] | None) -> list[uuid.UUID]:
    if selected:
        return [uuid.UUID(s) for s in selected]
    return list(db.scalars(select(Student.id).order_by(Student.created_at)))


def analyzed_games(db: Session, student_id: uuid.UUID) -> list[tuple[Game, list[MoveAnalysis]]]:
    """Mapped, analyzed games (oldest first) with their latest evidence rows."""
    games = db.scalars(
        select(Game).where(
            Game.student_id == student_id,
            Game.mapping_status.in_((MappingStatus.MAPPED, MappingStatus.CONFIRMED)),
        )
    )
    out = []
    for game in games:
        try:
            _, _, moves = latest_evidence(db, game)
        except ConflictError:
            continue
        out.append((game, moves))
    out.sort(key=lambda gm: (gm[0].played_at is None, gm[0].played_at, gm[0].created_at))
    return out


def classifier_labels(db: Session, game_ids: list[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
    """What the CLASSIFIER said per move, before any coach review: corrected findings use
    their original label, rejected findings still count as predictions."""
    out: dict[uuid.UUID, set[str]] = {}
    rows = db.scalars(
        select(WeaknessObservation).where(
            WeaknessObservation.game_id.in_(game_ids),
            WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
        )
    )
    for o in rows:
        original = o.details.get("original")
        label = (
            label_of(original["skill_code"], original["subskill_code"])
            if original
            else label_of(o.skill_code, o.subskill_code)
        )
        out.setdefault(o.move_analysis_id, set()).add(label)
    return out
