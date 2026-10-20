"""Walk a game and produce engine evidence for each of the student's moves.

No database access: input is PGN text + the student's color; output is plain records.
"""

import io
from collections.abc import Collection
from dataclasses import dataclass, field

import chess
import chess.pgn

from chesscoach.analysis.engine import EngineLine, PositionAnalyzer
from chesscoach.analysis.phase import PHASE_RULES_VERSION, classify_phase, material_balance
from chesscoach.analysis.scores import (
    SCORES_VERSION,
    Evaluation,
    MateTransition,
    checkmate_delivered,
    from_pov_score,
    is_critical,
    move_loss,
    win_probability,
)
from chesscoach.db.enums import Color, GamePhase

# v2: also stores the engine's best reply to the student's move (`refutation_pv`), which
# the motif detectors need to check what a move allowed.
ANALYSIS_VERSION = "analysis-v2"


@dataclass
class MoveRecord:
    ply: int  # 1-based half-move number of the student's move
    fen_before: str
    fen_after: str
    uci_move: str
    san_move: str
    phase: GamePhase
    eval_before: Evaluation
    eval_after: Evaluation
    best_move_uci: str | None
    principal_variation: list[str]
    second_best: Evaluation | None
    cp_loss: int | None
    win_prob_loss: float
    transition: MateTransition
    search_depth: int | None
    clock_before_ms: int | None
    clock_after_ms: int | None
    critical: bool
    features: dict = field(default_factory=dict)


@dataclass
class AnalysisSettings:
    depth: int
    multipv: int
    critical_wp_loss: float


def versions() -> dict:
    return {
        "analysis_version": ANALYSIS_VERSION,
        "scores_version": SCORES_VERSION,
        "phase_rules_version": PHASE_RULES_VERSION,
    }


def analyze_game(
    raw_pgn: str,
    student_color: Color,
    analyzer: PositionAnalyzer,
    settings: AnalysisSettings,
    *,
    game_key: object,
    only_plies: Collection[int] | None = None,
) -> list[MoveRecord]:
    game = chess.pgn.read_game(io.StringIO(raw_pgn))
    if game is None or game.errors:
        raise ValueError("Stored PGN could not be re-parsed cleanly")

    color = chess.WHITE if student_color == Color.WHITE else chess.BLACK
    board = game.board()
    records: list[MoveRecord] = []
    last_student_clock_ms: int | None = None

    for node in game.mainline():
        move = node.move
        ply = board.ply() + 1
        is_student = board.turn == color
        clock_after_ms = _clock_ms(node)

        if not is_student or (only_plies is not None and ply not in only_plies):
            if is_student:
                last_student_clock_ms = clock_after_ms
            board.push(move)
            continue

        fen_before = board.fen()
        san = board.san(move)
        phase = classify_phase(board)
        features = _position_features(board, move, color)

        before_lines = analyzer.analyse(
            board, depth=settings.depth, multipv=settings.multipv, game_key=game_key
        )
        if not before_lines:
            raise RuntimeError(f"Engine returned no evaluation at ply {ply}")
        best = before_lines[0]
        eval_before = from_pov_score(best.score, color)
        second_best = (
            from_pov_score(before_lines[1].score, color) if len(before_lines) > 1 else None
        )
        best_move = best.pv[0] if best.pv else None

        board.push(move)
        fen_after = board.fen()
        eval_after, after_depth, reply_pv = _evaluate_after(
            board, color, analyzer, settings, game_key
        )
        played_best = best_move is not None and move == best_move
        loss = move_loss(eval_before, eval_after, played_best=played_best)

        features.update(
            {
                "played_best": played_best,
                "legal_moves": features.pop("_legal_moves"),
                "only_move_gap_wp": _gap(eval_before, second_best),
                "pv_san": _pv_san(fen_before, best.pv),
                "after_search_depth": after_depth,
                "refutation_pv": [m.uci() for m in reply_pv],
                "refutation_san": _pv_san(fen_after, reply_pv),
            }
        )
        if board.is_game_over():
            features["terminal"] = board.outcome().termination.name.lower()

        records.append(
            MoveRecord(
                ply=ply,
                fen_before=fen_before,
                fen_after=fen_after,
                uci_move=move.uci(),
                san_move=san,
                phase=phase,
                eval_before=eval_before,
                eval_after=eval_after,
                best_move_uci=best_move.uci() if best_move else None,
                principal_variation=[m.uci() for m in best.pv],
                second_best=second_best,
                cp_loss=loss.cp_loss,
                win_prob_loss=loss.win_prob_loss,
                transition=loss.transition,
                search_depth=best.depth,
                clock_before_ms=last_student_clock_ms,
                clock_after_ms=clock_after_ms,
                critical=is_critical(loss, settings.critical_wp_loss),
                features=features,
            )
        )
        last_student_clock_ms = clock_after_ms

    return records


def _evaluate_after(
    board, color, analyzer, settings, game_key
) -> tuple[Evaluation, int | None, list[chess.Move]]:
    """Evaluate the position after the student's move, handling terminal positions ourselves.

    Engines report a checkmated side-to-move as Mate(-0), whose sign is lost after POV
    normalization, so terminal results are derived from the rules instead.
    """
    if board.is_checkmate():
        return checkmate_delivered(), None, []
    if board.is_stalemate() or board.is_insufficient_material():
        return Evaluation(cp=0), None, []
    lines: list[EngineLine] = analyzer.analyse(
        board, depth=settings.depth, multipv=1, game_key=game_key
    )
    if not lines:
        raise RuntimeError("Engine returned no evaluation after move")
    return from_pov_score(lines[0].score, color), lines[0].depth, lines[0].pv


def _position_features(board: chess.Board, move: chess.Move, color: chess.Color) -> dict:
    return {
        "material_balance": material_balance(board, color),
        "in_check": board.is_check(),
        "is_capture": board.is_capture(move),
        "gives_check": board.gives_check(move),
        "_legal_moves": board.legal_moves.count(),
    }


def _gap(best: Evaluation, second: Evaluation | None) -> float | None:
    """Win-probability gap between the best and second-best line (large = only move)."""
    if second is None:
        return None
    return round(max(0.0, win_probability(best) - win_probability(second)), 6)


def _pv_san(fen: str, pv: list[chess.Move], limit: int = 10) -> list[str]:
    board = chess.Board(fen)
    sans = []
    for move in pv[:limit]:
        if move not in board.legal_moves:
            break  # never store an illegal line
        sans.append(board.san(move))
        board.push(move)
    return sans


def _clock_ms(node: chess.pgn.ChildNode) -> int | None:
    seconds = node.clock()
    return int(round(seconds * 1000)) if seconds is not None else None
