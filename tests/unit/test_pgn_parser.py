from datetime import date

import pytest

from chesscoach.db.enums import GameResult
from chesscoach.ingestion.pgn_parser import (
    compute_game_hash,
    decode_pgn_bytes,
    normalize_name,
    parse_pgn_date,
    parse_pgn_text,
)


@pytest.fixture
def parsed(mixed_pgn):
    text, _, _ = decode_pgn_bytes(mixed_pgn)
    return parse_pgn_text(text)


def test_parses_valid_games_and_rejects_illegal(parsed):
    assert [g.index for g in parsed.games] == [0, 1, 2, 4]
    assert len(parsed.rejected) == 1
    rejected = parsed.rejected[0]
    assert rejected.index == 3
    assert "illegal" in rejected.reason.lower()


def test_extracts_metadata(parsed):
    g0 = parsed.games[0]
    assert (g0.white, g0.black) == ("Ovindu", "Opponent A")
    assert g0.result == GameResult.WHITE_WIN
    assert g0.played_at == date(2024, 3, 1)
    assert g0.time_control == "600+5"
    assert g0.eco == "C20"
    assert g0.ply_count == 7
    assert g0.uci_moves[-1] == "h5f7"
    assert g0.has_clock is True
    assert g0.warnings == []


def test_partial_date_is_none_with_warning(parsed):
    g1 = parsed.games[1]
    assert g1.played_at is None
    assert g1.has_clock is False
    assert any("date" in w.lower() for w in g1.warnings)


def test_raw_pgn_slice_contains_only_its_own_game(parsed):
    for g in parsed.games:
        assert g.raw_pgn.startswith("[Event")
        assert g.raw_pgn.count("[Event ") == 1
    assert "Qxf7#" in parsed.games[0].raw_pgn


def test_game_hash_ignores_case_and_whitespace_in_names():
    moves = ["e2e4", "e7e5"]
    a = compute_game_hash({"White": "Ovindu  M", "Black": "X"}, moves)
    b = compute_game_hash({"White": "ovindu m", "Black": "x"}, moves)
    c = compute_game_hash({"White": "ovindu m", "Black": "x"}, ["e2e4", "c7c5"])
    assert a == b
    assert a != c


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2024.03.01", date(2024, 3, 1)),
        ("2024.??.??", None),
        ("????.??.??", None),
        ("2024.13.01", None),
        (None, None),
    ],
)
def test_parse_pgn_date(value, expected):
    assert parse_pgn_date(value) == expected


def test_decode_latin1_fallback_warns():
    text, encoding, warnings = decode_pgn_bytes('[White "Jos\xe9"]'.encode("latin-1"))
    assert encoding == "latin-1"
    assert "José" in text
    assert warnings


def test_decode_rejects_binary():
    with pytest.raises(ValueError):
        decode_pgn_bytes(b"\x00\x01\x02")


def test_normalize_name():
    assert normalize_name("  Magnus   CARLSEN ") == "magnus carlsen"


def test_custom_start_position_is_rejected():
    pgn = (
        '[White "A"]\n[Black "B"]\n[SetUp "1"]\n[FEN "8/8/8/8/8/8/4K3/4k3 w - - 0 1"]\n\n1. Kd3 *\n'
    )
    result = parse_pgn_text(pgn)
    assert not result.games
    assert "starting position" in result.rejected[0].reason
