from chesscoach.db.enums import Color, MappingStatus
from chesscoach.ingestion.identity import resolve_student_color

ALIASES = {"ovindu", "ovindu_m"}


def test_white_match():
    assert resolve_student_color("Ovindu", "Someone", ALIASES) == (
        MappingStatus.MAPPED,
        Color.WHITE,
    )


def test_black_match_case_insensitive():
    assert resolve_student_color("X", " OVINDU_M ", ALIASES) == (MappingStatus.MAPPED, Color.BLACK)


def test_no_match_is_unmatched():
    assert resolve_student_color("A", "B", ALIASES) == (MappingStatus.UNMATCHED, None)


def test_both_match_is_ambiguous_never_guessed():
    assert resolve_student_color("Ovindu", "ovindu_m", ALIASES) == (MappingStatus.AMBIGUOUS, None)


def test_no_aliases_is_unmatched():
    assert resolve_student_color("Ovindu", "B", set()) == (MappingStatus.UNMATCHED, None)
