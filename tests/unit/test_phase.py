import chess

from chesscoach.analysis.phase import classify_phase, material_balance
from chesscoach.db.enums import GamePhase


def test_start_position_is_opening():
    assert classify_phase(chess.Board()) == GamePhase.OPENING


def test_rook_endgame():
    board = chess.Board("8/5pk1/6p1/8/8/6P1/r4PK1/R7 w - - 0 40")
    assert classify_phase(board) == GamePhase.ENDGAME


def test_late_full_board_is_middlegame():
    board = chess.Board()
    board.fullmove_number = 20
    assert classify_phase(board) == GamePhase.MIDDLEGAME


def test_material_balance_perspective():
    board = chess.Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")  # White has an extra queen
    assert material_balance(board, chess.WHITE) == 9
    assert material_balance(board, chess.BLACK) == -9
