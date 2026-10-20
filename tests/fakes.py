"""Deterministic stand-in for Stockfish so analysis logic can be tested without an engine."""

import chess
import chess.engine

from chesscoach.analysis.engine import EngineIdentity, EngineLine
from chesscoach.analysis.phase import material_balance


class FakeAnalyzer:
    """One-ply greedy engine: mate-in-1 beats everything, otherwise material after the move.

    Good enough to exercise perspective handling, MultiPV, mates and persistence. It is
    not a chess engine and must never be used for real analysis.
    """

    def __init__(self, fail_times: int = 0, fail_always: bool = False):
        self.identity = EngineIdentity(
            name="FakeFish", version="1.0", checksum="0" * 64, options={"Threads": 1}
        )
        self.calls = 0
        self.fail_times = fail_times
        self.fail_always = fail_always

    def analyse(self, board: chess.Board, *, depth: int, multipv: int, game_key: object):
        self.calls += 1
        if self.fail_always or self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("simulated engine failure")
        mover = board.turn
        scored = []
        for move in sorted(board.legal_moves, key=lambda m: m.uci()):
            board.push(move)
            if board.is_checkmate():
                score = chess.engine.PovScore(chess.engine.Mate(1), mover)
            else:
                score = chess.engine.PovScore(
                    chess.engine.Cp(100 * material_balance(board, mover)), mover
                )
            board.pop()
            scored.append((score, move))
        scored.sort(key=lambda sm: sm[0].pov(mover), reverse=True)
        return [EngineLine(score=s, pv=[m], depth=depth) for s, m in scored[:multipv]]
