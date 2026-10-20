import chess
import pytest

from chesscoach.classification.motifs import (
    capturable_for_profit,
    detect_allowed,
    detect_missed,
    fork_targets,
)

KNIGHT_FORK = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"  # Nc7+ forks Ke8 and Ra8
FREE_QUEEN = "4k3/8/8/3q4/8/8/6B1/4K3 w - - 0 1"  # Bxd5 wins an undefended queen
EQUAL_TRADE = "4k3/8/4p3/3n4/8/2N5/8/4K3 w - - 0 1"  # Nxd5 exd5: knight defended by pawn
PAWN_TAKES_KNIGHT = "4k3/8/4p3/3n4/4P3/8/8/4K3 w - - 0 1"  # exd5 wins a piece for a pawn


def test_knight_fork_is_detected_in_best_move():
    motifs = detect_missed(KNIGHT_FORK, "b5c7", None)
    assert [m.subskill for m in motifs] == ["forks"]
    assert motifs[0].kind == "missed"
    assert sorted(motifs[0].details["targets"]) == ["a8", "e8"]


def test_undefended_piece_capture_is_hanging():
    motifs = detect_missed(FREE_QUEEN, "g2d5", None)
    assert [m.subskill for m in motifs] == ["hanging_pieces"]
    assert motifs[0].details == {"captured": "q", "square": "d5"}


def test_defended_equal_piece_is_not_hanging():
    assert detect_missed(EQUAL_TRADE, "c3d5", None) == []


def test_cheaper_capturer_wins_defended_piece():
    motifs = detect_missed(PAWN_TAKES_KNIGHT, "e4d5", None)
    assert [m.subskill for m in motifs] == ["hanging_pieces"]


def test_mate_score_dominates():
    motifs = detect_missed(KNIGHT_FORK, "b5c7", 2)
    assert [(m.subskill, m.details) for m in motifs] == [("mating_patterns", {"mate_in": 2})]


@pytest.mark.parametrize("move", [None, "a1a8"])  # missing, or illegal in this position
def test_missing_or_illegal_best_move_gives_nothing(move):
    assert detect_missed(KNIGHT_FORK, move, None) == []


def test_allowed_fork_in_opponent_reply():
    after_student_move = "4k3/8/8/8/1n6/8/8/R3K3 b - - 0 1"  # ...Nc2+ forks Ke1 and Ra1
    motifs = detect_allowed(after_student_move, "b4c2")
    assert [m.subskill for m in motifs] == ["forks"]
    assert motifs[0].kind == "allowed"


def test_pinned_piece_cannot_capture_for_profit():
    # The white bishop on e2 is pinned to the king by the rook on e8, so it cannot take b5.
    board = chess.Board("4r1k1/8/8/1q6/8/8/4B3/4K3 w - - 0 1")
    assert not capturable_for_profit(board, chess.B5)


def test_fork_needs_two_valuable_targets():
    board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    board.set_piece_at(chess.C7, chess.Piece(chess.KNIGHT, chess.WHITE))
    board.set_piece_at(chess.A8, chess.Piece(chess.PAWN, chess.BLACK))
    assert fork_targets(board, chess.C7) == []  # king only; pawn is not a target
