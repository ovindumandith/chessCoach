"""Reclassify every analyzed game and rebuild profiles after a classifier change.

    python -m chesscoach.classification.reclassify [--student <uuid>]

Engine analysis is reused, never redone. Coach reviews from older classifier versions are
carried forward (see service.classify_game). Older-version rows are kept as history.
"""

import argparse
import logging
import uuid

from sqlalchemy import select

from chesscoach.classification.service import classify_game
from chesscoach.core.errors import ConflictError
from chesscoach.db.enums import MappingStatus
from chesscoach.db.models import Game
from chesscoach.db.session import get_sessionmaker
from chesscoach.profiling.service import rebuild_profile

log = logging.getLogger("chesscoach.reclassify")


def reclassify_all(student_id: uuid.UUID | None = None) -> dict:
    stats = {"games": 0, "skipped_unanalyzed": 0, "carried_reviews": 0, "profiles": 0}
    with get_sessionmaker()() as db:
        query = select(Game.id, Game.student_id).where(
            Game.mapping_status.in_((MappingStatus.MAPPED, MappingStatus.CONFIRMED))
        )
        if student_id is not None:
            query = query.where(Game.student_id == student_id)
        students = set()
        for game_id, sid in db.execute(query).all():
            try:
                result = classify_game(db, game_id)
            except ConflictError:
                stats["skipped_unanalyzed"] += 1
                continue
            stats["games"] += 1
            stats["carried_reviews"] += result.carried_reviews
            students.add(sid)
        for sid in students:
            if rebuild_profile(db, sid, triggered_by="reclassify").created:
                stats["profiles"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--student", type=uuid.UUID, help="Only this student")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(reclassify_all(args.student))


if __name__ == "__main__":
    main()
