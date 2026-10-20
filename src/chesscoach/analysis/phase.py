"""Game-phase classification.

Simplified from Lichess's `Divider`: phase depends on the number of minor and major pieces
left on the board and on move number. Deliberately simple and versioned so it can be
compared against coach labels later.
"""

import chess

from chesscoach.db.enums import GamePhase

PHASE_RULES_VERSION = "phase-v1"

ENDGAME_MAX_PIECES = 6  # minors + majors, both sides
OPENING_MIN_PIECES = 11  # more than 10 minors + majors still on the board
OPENING_MAX_FULLMOVE = 12

_PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def count_minors_and_majors(board: chess.Board) -> int:
    return sum(
        len(board.pieces(pt, color))
        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
        for color in chess.COLORS
    )


def classify_phase(board: chess.Board) -> GamePhase:
    pieces = count_minors_and_majors(board)
    if pieces <= ENDGAME_MAX_PIECES:
        return GamePhase.ENDGAME
    if board.fullmove_number <= OPENING_MAX_FULLMOVE and pieces >= OPENING_MIN_PIECES:
        return GamePhase.OPENING
    return GamePhase.MIDDLEGAME


def material_balance(board: chess.Board, color: chess.Color) -> int:
    """Material difference in pawn units from `color`'s point of view."""
    total = 0
    for pt, value in _PIECE_VALUES.items():
        total += value * (len(board.pieces(pt, color)) - len(board.pieces(pt, not color)))
    return total
