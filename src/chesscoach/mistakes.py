"""The student's mistakes, grouped by game, with acknowledgements.

A mistake is one of the student's own moves that has a current finding (the classifier
stores one for every non-forced move from inaccuracy upwards, as `unclassified` when no
cause is verified). The display comes from the annotation module (verdict, reason, better
move); the mistake types and "same mistake before" links come from the findings.

Acknowledging is the student saying "I have seen this". It is display and monitoring only:
it never changes a finding or the profile. When an acknowledged kind of mistake shows up
again in a later game, that later mistake is flagged.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.analysis.service import analysis_states
from chesscoach.annotation.service import game_annotations
from chesscoach.classification.classifier import CLASSIFIER_VERSION
from chesscoach.classification.service import game_findings
from chesscoach.core.access import require_own_student_record, require_student_access
from chesscoach.core.audit import record_audit
from chesscoach.core.errors import NotFoundError, ValidationFailedError
from chesscoach.db.enums import Color, MappingStatus, ReviewStatus
from chesscoach.db.models import (
    Game,
    MistakeAcknowledgement,
    MoveAnalysis,
    User,
    WeaknessObservation,
)
from chesscoach.db.types import utcnow

READY = ("analyzed", "deepening")
RESOLVED = (MappingStatus.MAPPED, MappingStatus.CONFIRMED)


def _when(g: Game):
    return (g.played_at is not None, g.played_at or date.min, g.created_at)


def _acks(db: Session, student_id: uuid.UUID) -> dict[tuple[str, int], MistakeAcknowledgement]:
    rows = db.scalars(
        select(MistakeAcknowledgement).where(MistakeAcknowledgement.student_id == student_id)
    )
    return {(str(a.game_id), a.ply): a for a in rows}


def student_mistakes(
    db: Session, user: User, student_id: uuid.UUID, *, limit: int = 10, offset: int = 0
) -> dict:
    """Analyzed games, newest first, each with the student's mistakes in move order."""
    require_student_access(db, user, student_id)
    games = list(
        db.scalars(
            select(Game).where(Game.student_id == student_id, Game.mapping_status.in_(RESOLVED))
        )
    )
    states = analysis_states(db, [g.id for g in games])
    ready = sorted((g for g in games if states.get(g.id) in READY), key=_when, reverse=True)
    acks = _acks(db, student_id)

    out = []
    for game in ready[offset : offset + limit]:
        notes = {a["ply"]: a for a in game_annotations(db, user, game.id)["annotations"]}
        by_ply: dict[int, list[dict]] = {}
        for f in game_findings(db, user, game.id)["findings"]:
            by_ply.setdefault(f["ply"], []).append(f)

        mistakes = []
        for ply in sorted(by_ply):
            note = notes.get(ply, {})
            types = []
            flagged_again = None
            for f in by_ply[ply]:
                earlier = [
                    {**o, "acknowledged": (o["game_id"], o["ply"]) in acks}
                    for o in f["same_mistake_elsewhere"]
                    if o["earlier"]
                ]
                seen = next((o for o in earlier if o["acknowledged"]), None)
                if seen and flagged_again is None:
                    flagged_again = seen
                types.append(
                    {
                        "skill_code": f["skill_code"],
                        "subskill_code": f["subskill_code"],
                        "motif_kind": f["motif_kind"],
                        "evidence_type": f["evidence_type"],
                        "earlier": earlier,
                    }
                )
            ack = acks.get((str(game.id), ply))
            mistakes.append(
                {
                    "ply": ply,
                    "move_number": (ply + 1) // 2,
                    "san": note.get("san") or by_ply[ply][0]["san_move"],
                    "verdict": note.get("verdict"),
                    "label": note.get("label"),
                    "symbol": note.get("symbol"),
                    "eval_before": note.get("eval_before"),
                    "eval_after": note.get("eval_after"),
                    "best_move_san": note.get("best_move_san"),
                    "best_line_san": note.get("best_line_san", []),
                    "reasons": note.get("reasons", []),
                    "types": types,
                    "acknowledged_at": ack.acknowledged_at.isoformat() if ack else None,
                    # An earlier mistake of the same kind that the student already acknowledged.
                    "flagged_again": flagged_again,
                }
            )
        white = game.student_color == Color.WHITE
        out.append(
            {
                "game_id": str(game.id),
                "white_name": game.white_name,
                "black_name": game.black_name,
                "student_color": game.student_color.value if game.student_color else None,
                "opponent": game.black_name if white else game.white_name,
                "result": game.result.value,
                "played_at": game.played_at.isoformat() if game.played_at else None,
                "mistakes": mistakes,
                "acknowledged": sum(1 for m in mistakes if m["acknowledged_at"]),
            }
        )
    return {"total_games": len(ready), "limit": limit, "offset": offset, "games": out}


def _student_move(db: Session, user: User, game_id: uuid.UUID, ply: int) -> Game:
    game = db.get(Game, game_id)
    if game is None:
        raise NotFoundError("Game not found")
    require_own_student_record(db, user, game.student_id)
    if game.student_color is None or not 1 <= ply <= game.ply_count:
        raise ValidationFailedError("Not a move of this game")
    if (ply % 2 == 1) != (game.student_color == Color.WHITE):
        raise ValidationFailedError("Only your own moves can be acknowledged")
    return game


def acknowledge(db: Session, user: User, game_id: uuid.UUID, ply: int) -> MistakeAcknowledgement:
    """The student acknowledges their mistake on this move. Idempotent."""
    game = _student_move(db, user, game_id, ply)
    ack = db.scalar(
        select(MistakeAcknowledgement).where(
            MistakeAcknowledgement.game_id == game.id, MistakeAcknowledgement.ply == ply
        )
    )
    if ack is None:
        ack = MistakeAcknowledgement(
            student_id=game.student_id,
            game_id=game.id,
            ply=ply,
            acknowledged_by=user.id,
            acknowledged_at=utcnow(),
        )
        db.add(ack)
        record_audit(
            db,
            actor_user_id=user.id,
            action="mistake.acknowledge",
            entity_type="game",
            entity_id=game.id,
            details={"ply": ply},
        )
        db.commit()
    return ack


def unacknowledge(db: Session, user: User, game_id: uuid.UUID, ply: int) -> None:
    game = _student_move(db, user, game_id, ply)
    ack = db.scalar(
        select(MistakeAcknowledgement).where(
            MistakeAcknowledgement.game_id == game.id, MistakeAcknowledgement.ply == ply
        )
    )
    if ack is not None:
        db.delete(ack)
        db.commit()


def open_mistake_counts(db: Session, student_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Per student: mistakes (moves with a current finding) and how many are acknowledged.
    Callers check access."""
    if not student_ids:
        return {}
    rows = db.execute(
        select(WeaknessObservation.student_id, WeaknessObservation.game_id, MoveAnalysis.ply)
        .join(MoveAnalysis, MoveAnalysis.id == WeaknessObservation.move_analysis_id)
        .where(
            WeaknessObservation.student_id.in_(student_ids),
            WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
            WeaknessObservation.review_status != ReviewStatus.REJECTED,
        )
        .distinct()
    ).all()
    acked = acknowledged_moves(db, student_ids)
    out = {sid: {"mistakes": 0, "acknowledged": 0} for sid in student_ids}
    for sid, gid, ply in rows:
        out[sid]["mistakes"] += 1
        out[sid]["acknowledged"] += (gid, ply) in acked
    return out


def acknowledged_moves(db: Session, student_ids: list[uuid.UUID]) -> set[tuple[uuid.UUID, int]]:
    if not student_ids:
        return set()
    return set(
        db.execute(
            select(MistakeAcknowledgement.game_id, MistakeAcknowledgement.ply).where(
                MistakeAcknowledgement.student_id.in_(student_ids)
            )
        ).all()
    )
