"""Annotate every move of an analyzed game, for the student AND the opponent.

Opponent moves need no extra engine work. Around an opponent move the stored analysis
already has:
- before: the position after the student's previous move (with the opponent's best reply,
  `refutation_pv`, as the opponent's best move), and
- after: the position before the student's next move (with the student's best line, which
  is how the opponent's mistake could be punished).
Both evaluations come from the same fixed-depth searches used for the student's moves.
"""

import io
import uuid

import chess
import chess.pgn
from sqlalchemy.orm import Session

from chesscoach.analysis.scores import Evaluation, MateTransition, move_loss, win_probability
from chesscoach.annotation.explain import OPPONENT, YOU, explain
from chesscoach.classification.classifier import THRESHOLDS
from chesscoach.classification.service import latest_evidence
from chesscoach.core.access import require_student_access
from chesscoach.core.errors import NotFoundError
from chesscoach.db.models import Game, MoveAnalysis, User

SERIOUS = {
    MateTransition.MISSED_MATE: "Missed a forced mate",
    MateTransition.ALLOWED_MATE: "Allowed a forced mate",
    MateTransition.MATE_TO_MATED: "Turned a winning mate into a losing one",
}
VERDICT = {
    "best": ("Best move", "✓"),
    "good": ("Good move", ""),
    "inaccuracy": ("Inaccuracy", "?!"),
    "mistake": ("Mistake", "?"),
    "blunder": ("Blunder", "??"),
}


def verdict_kind(wp_loss: float, transition: MateTransition, played_best: bool) -> str:
    """Same thresholds as the classifier, so display and findings always agree."""
    if transition in SERIOUS:
        return "blunder"
    if played_best:
        return "best"
    if wp_loss >= THRESHOLDS["blunder"]:
        return "blunder"
    if wp_loss >= THRESHOLDS["mistake"]:
        return "mistake"
    if wp_loss >= THRESHOLDS["inaccuracy"]:
        return "inaccuracy"
    return "good"


def _eval(cp: int | None, mate: int | None) -> Evaluation | None:
    if mate is not None:
        return Evaluation(mate=mate)
    return Evaluation(cp=cp) if cp is not None else None


def _flip(e: Evaluation | None) -> Evaluation | None:
    if e is None:
        return None
    return Evaluation(mate=-e.mate) if e.mate is not None else Evaluation(cp=-e.cp)


def _white(e: Evaluation | None, mover: chess.Color) -> dict:
    """An evaluation from White's point of view (+ = White better), for display."""
    if e is None:
        return {"cp": None, "mate": None}
    if e.mate == 0:  # the mover just delivered checkmate; say who, since 0 has no sign
        return {"cp": None, "mate": 0, "mated": "black" if mover == chess.WHITE else "white"}
    w = e if mover == chess.WHITE else _flip(e)
    return {"cp": w.cp, "mate": w.mate}


def _entry(
    ply,
    side,
    san,
    fen_before,
    kind,
    label,
    before,
    after,
    mover,
    wp_loss,
    best_line_san,
    reasons,
    best_uci,
    reply_uci,
):
    label_text, symbol = VERDICT[kind]
    return {
        "ply": ply,
        "side": side,  # "student" | "opponent"
        "san": san,
        "fen_before": fen_before,
        "verdict": kind,
        "label": label or label_text,
        "symbol": symbol,
        "eval_before": _white(before, mover),
        "eval_after": _white(after, mover),
        "win_prob_loss": round(wp_loss, 4),
        "best_move_san": best_line_san[0] if best_line_san else None,
        "best_move_uci": best_uci,
        "best_line_san": best_line_san[:8],
        "threat_uci": reply_uci,
        "reasons": reasons,
    }


def _student_entry(m: MoveAnalysis, color: chess.Color) -> dict:
    f = m.features or {}
    before = _eval(m.eval_before_cp, m.eval_before_mate)
    after = _eval(m.eval_after_cp, m.eval_after_mate)
    transition = MateTransition(f.get("mate_transition", "none"))
    kind = verdict_kind(m.win_prob_loss or 0.0, transition, bool(f.get("played_best")))
    reasons = explain(
        fen_before=m.fen_before,
        played_uci=m.uci_move,
        best_line=list(m.principal_variation or []),
        reply_line=list(f.get("refutation_pv") or []),
        before=before,
        after=after,
        transition=transition,
        actor=YOU,
        is_mistake=kind in ("inaccuracy", "mistake", "blunder"),
    )
    return _entry(
        m.ply,
        "student",
        m.san_move,
        m.fen_before,
        kind,
        SERIOUS.get(transition),
        before,
        after,
        color,
        m.win_prob_loss or 0.0,
        f.get("pv_san", []),
        reasons,
        m.best_move_uci,
        (f.get("refutation_pv") or [None])[0],
    )


def _opponent_entry(
    ply: int, board: chess.Board, move: chess.Move, prev: MoveAnalysis, nxt: MoveAnalysis | None
) -> dict | None:
    """Grade an opponent move from the student's surrounding analysis (opponent's side)."""
    mover = board.turn
    after_board = board.copy()
    after_board.push(move)
    before = _flip(_eval(prev.eval_after_cp, prev.eval_after_mate))
    if after_board.is_checkmate():
        after = Evaluation(mate=0)
    elif nxt is not None:
        after = _flip(_eval(nxt.eval_before_cp, nxt.eval_before_mate))
    else:
        return None  # last move of the game and not mate: nothing to compare against
    if before is None or after is None:
        return None
    best_line = list((prev.features or {}).get("refutation_pv") or [])
    played_best = bool(best_line) and best_line[0] == move.uci()
    loss = move_loss(before, after, played_best=played_best)  # delivered mate scores as no loss
    kind = verdict_kind(loss.win_prob_loss, loss.transition, played_best)
    reply_line = list(nxt.principal_variation or []) if nxt is not None else []
    reasons = explain(
        fen_before=board.fen(),
        played_uci=move.uci(),
        best_line=best_line,
        reply_line=reply_line,
        before=before,
        after=after,
        transition=loss.transition,
        actor=OPPONENT,
        is_mistake=kind in ("inaccuracy", "mistake", "blunder"),
    )
    best_san = list((prev.features or {}).get("refutation_san") or [])
    return _entry(
        ply,
        "opponent",
        board.san(move),
        board.fen(),
        kind,
        SERIOUS.get(loss.transition),
        before,
        after,
        mover,
        loss.win_prob_loss,
        best_san,
        reasons,
        best_line[0] if best_line else None,
        reply_line[0] if reply_line else None,
    )


def game_annotations(db: Session, user: User, game_id: uuid.UUID) -> dict:
    game = db.get(Game, game_id)
    if game is None:
        raise NotFoundError("Game not found")
    require_student_access(db, user, game.student_id)
    _, _, rows = latest_evidence(db, game)  # ConflictError (409) until analyzed
    by_ply = {m.ply: m for m in rows}
    student = (
        chess.WHITE if game.student_color and game.student_color.value == "white" else chess.BLACK
    )

    pgn = chess.pgn.read_game(io.StringIO(game.raw_pgn))
    board = pgn.board()
    out = []
    for node in pgn.mainline():
        ply = board.ply() + 1
        if board.turn == student:
            if ply in by_ply:
                out.append(_student_entry(by_ply[ply], student))
        elif ply - 1 in by_ply:
            entry = _opponent_entry(ply, board, node.move, by_ply[ply - 1], by_ply.get(ply + 1))
            if entry:
                out.append(entry)
        board.push(node.move)
    return {
        "game_id": str(game.id),
        "student_color": "white" if student == chess.WHITE else "black",
        "evaluation_convention": "+ = White is better, - = Black is better (pawn units)",
        "note": "Opponent moves are graded from the same stored analysis; they never count "
        "toward the student's profile.",
        "annotations": out,
        "win_chance_white": {str(a["ply"]): _white_chance(a["eval_after"]) for a in out},
    }


def _white_chance(e: dict) -> float | None:
    if e["mate"] is not None:
        if e["mate"] == 0:
            return 1.0 if e.get("mated") == "black" else 0.0
        return 1.0 if e["mate"] > 0 else 0.0
    return round(win_probability(Evaluation(cp=e["cp"])), 4) if e["cp"] is not None else None
