"""Tactical motif detectors built only on python-chess board facts.

Detectors answer narrow, checkable questions ("does this move attack two valuable
targets?"). They never decide on their own that a motif *mattered*: the classifier only
reports a motif when the engine evidence agrees (see classifier.py). Known simplifications,
all biased toward NOT reporting a motif:
- "Capturable for profit" ignores x-rays and multi-step exchanges. Pinned defenders still
  count as defenders.
- Pawns are ignored as hanging or fork targets (too noisy for v1).
"""

from dataclasses import dataclass, field

import chess

MOTIFS_VERSION = "motifs-v1"

VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}
MIN_TARGET_VALUE = 3


@dataclass
class Motif:
    subskill: str  # tactical_awareness.<subskill>
    kind: str  # "missed" (in the engine's best move) or "allowed" (in the engine's reply)
    details: dict = field(default_factory=dict)


def capturable_for_profit(board: chess.Board, square: chess.Square) -> bool:
    """Can the side to move legally win the piece on `square`?

    True when the piece is undefended, or when the cheapest legal capturer is worth less
    than the piece.
    """
    target = board.piece_at(square)
    if target is None or target.color == board.turn:
        return False
    capturers = [
        board.piece_type_at(m.from_square)
        for m in board.legal_moves
        if m.to_square == square and board.is_capture(m)
    ]
    if not capturers:
        return False
    if not board.attackers(target.color, square):
        return True
    return min(VALUES[pt] for pt in capturers) < VALUES[target.piece_type]


def fork_targets(board: chess.Board, square: chess.Square) -> list[chess.Square]:
    """Valuable enemy pieces attacked by the piece on `square` (the move was just played).

    A target counts if it is the king, worth more than the forking piece, or undefended
    and worth at least a minor piece. Returns an empty list unless there are 2+ targets.
    """
    piece = board.piece_at(square)
    if piece is None:
        return []
    own_value = VALUES[piece.piece_type]
    targets = []
    for sq in board.attacks(square):
        victim = board.piece_at(sq)
        if victim is None or victim.color == piece.color:
            continue
        value = VALUES[victim.piece_type]
        if (
            victim.piece_type == chess.KING
            or value > own_value
            or (value >= MIN_TARGET_VALUE and not board.attackers(victim.color, sq))
        ):
            targets.append(sq)
    return targets if len(targets) >= 2 else []


def detect_in_move(board: chess.Board, move: chess.Move) -> list[Motif]:
    """Motifs created by `move` on `board`, which has the mover to play. Board unchanged."""
    motifs: list[Motif] = []
    victim = board.piece_at(move.to_square)
    if (
        victim is not None
        and board.is_capture(move)
        and VALUES[victim.piece_type] >= MIN_TARGET_VALUE
        and capturable_for_profit(board, move.to_square)
    ):
        motifs.append(
            Motif(
                "hanging_pieces",
                kind="",
                details={"captured": victim.symbol(), "square": chess.square_name(move.to_square)},
            )
        )
    board.push(move)
    try:
        if not board.is_checkmate():
            targets = fork_targets(board, move.to_square)
            if targets:
                motifs.append(
                    Motif(
                        "forks",
                        kind="",
                        details={
                            "forking_piece": board.piece_at(move.to_square).symbol(),
                            "targets": [chess.square_name(s) for s in targets],
                        },
                    )
                )
    finally:
        board.pop()
    return motifs


def detect_missed(fen_before: str, best_move_uci: str | None, best_mate: int | None) -> list[Motif]:
    """Motifs contained in the engine's best move for the student."""
    if best_mate is not None and best_mate > 0:
        return [Motif("mating_patterns", kind="missed", details={"mate_in": best_mate})]
    if not best_move_uci:
        return []
    board = chess.Board(fen_before)
    move = chess.Move.from_uci(best_move_uci)
    if move not in board.legal_moves:
        return []
    motifs = detect_in_move(board, move)
    for m in motifs:
        m.kind = "missed"
    return motifs


def detect_allowed(fen_after: str, refutation_uci: str | None) -> list[Motif]:
    """Motifs the opponent gets with the engine's best reply to the student's move."""
    if not refutation_uci:
        return []
    board = chess.Board(fen_after)
    move = chess.Move.from_uci(refutation_uci)
    if move not in board.legal_moves:
        return []
    motifs = detect_in_move(board, move)
    for m in motifs:
        m.kind = "allowed"
    return motifs
