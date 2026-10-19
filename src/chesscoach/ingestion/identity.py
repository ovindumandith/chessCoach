"""Student identity resolution from PGN player names. Never guesses on ambiguity."""

from collections.abc import Iterable

from chesscoach.db.enums import Color, MappingStatus
from chesscoach.ingestion.pgn_parser import normalize_name


def resolve_student_color(
    white: str, black: str, aliases: Iterable[str]
) -> tuple[MappingStatus, Color | None]:
    """Return the mapping status and, only when unambiguous, the student's color.

    `aliases` are already-normalized names known to belong to the student.
    """
    alias_set = set(aliases)
    white_match = normalize_name(white) in alias_set
    black_match = normalize_name(black) in alias_set
    if white_match and black_match:
        return MappingStatus.AMBIGUOUS, None
    if white_match:
        return MappingStatus.MAPPED, Color.WHITE
    if black_match:
        return MappingStatus.MAPPED, Color.BLACK
    return MappingStatus.UNMATCHED, None
