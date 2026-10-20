"""Plain-language reasons why a move was good or bad, derived only from stored engine lines
and the rules of chess (python-chess). Pure functions; nothing is guessed.

Reasons are produced in this order of strength:
1. forced mates (from the engine's mate scores);
2. material that changes hands when the engine's line is played out on the board;
3. verified tactical motifs (forks, undefended pieces) in the better move or the reply;
4. otherwise an honest "positional" statement with the engine's margin.
"""

from collections import Counter
from dataclasses import dataclass

import chess

from chesscoach.analysis.phase import material_balance
from chesscoach.analysis.scores import Evaluation, MateTransition
from chesscoach.classification.motifs import VALUES, detect_in_move

LINE_PLIES = 8  # how far the engine's line is played out when counting material
PIECE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}


@dataclass(frozen=True)
class Actor:
    """Who moved, in words: you / your opponent (and the matching verb forms)."""

    name: str  # "you" or "your opponent"
    other: str  # the other side, as an object: "your opponent" / "you"
    third_person: bool  # "loses" vs "lose"

    def verb(self, base: str) -> str:
        return f"{base}s" if self.third_person else base


YOU = Actor("you", "your opponent", third_person=False)
OPPONENT = Actor("your opponent", "you", third_person=True)


def _san_line(board: chess.Board, ucis: list[str], limit: int) -> tuple[list[str], chess.Board]:
    """SAN for a legal prefix of `ucis` (stops at the first illegal move) and the end board."""
    b = board.copy()
    out = []
    for u in ucis[:limit]:
        try:
            m = chess.Move.from_uci(u)
        except ValueError:
            break
        if m not in b.legal_moves:
            break
        out.append(b.san(m))
        b.push(m)
    return out, b


def _counts(board: chess.Board, color: chess.Color) -> Counter:
    return Counter({pt: len(board.pieces(pt, color)) for pt in PIECE_NAMES if pt != chess.KING})


def _describe(pieces: Counter) -> str:
    parts = []
    for pt in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN):
        n = pieces.get(pt, 0)
        if n == 1:
            parts.append(f"a {PIECE_NAMES[pt]}")
        elif n > 1:
            parts.append(f"{n} {PIECE_NAMES[pt]}s")
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _net_trades(lost: Counter, won: Counter) -> tuple[Counter, Counter, bool]:
    """Cancel even trades the way a player would describe them: same pieces cancel, a knight
    for a bishop cancels, and a rook for a minor piece is "the exchange"."""
    common = lost & won
    lost, won = lost - common, won - common
    for a, b in ((chess.KNIGHT, chess.BISHOP), (chess.BISHOP, chess.KNIGHT)):
        n = min(lost[a], won[b])
        lost[a] -= n
        won[b] -= n
    exchange = False
    for minor in (chess.KNIGHT, chess.BISHOP):
        if lost[chess.ROOK] and won[minor]:
            lost[chess.ROOK] -= 1
            won[minor] -= 1
            exchange = True
            break
    return +lost, +won, exchange


def material_outcome(start: chess.Board, end: chess.Board, mover: chess.Color) -> tuple[int, str]:
    """(net material change for `mover` in pawn units, phrase like "a knight for a pawn")."""
    net = material_balance(end, mover) - material_balance(start, mover)
    lost, won, exchange = _net_trades(
        _counts(start, mover) - _counts(end, mover),
        _counts(start, not mover) - _counts(end, not mover),
    )
    if net < 0:
        main, extra = _describe(lost), _describe(won)
        if exchange:
            main = "the exchange" + (f" and {main}" if main else "")
    else:
        main, extra = _describe(won), _describe(lost)
        if exchange:  # the mover gave up a rook for a minor piece but still came out ahead
            extra = "the exchange" + (f" and {extra}" if extra else "")
    if not main:
        return net, ""
    return net, main + (f" for {extra}" if extra else "")


def _motif_text(board: chess.Board, move: chess.Move) -> str | None:
    for m in detect_in_move(board, move):
        if m.subskill == "forks":
            after = board.copy()
            after.push(move)
            targets = [(after.piece_at(chess.parse_square(sq)), sq) for sq in m.details["targets"]]
            targets.sort(key=lambda t: -VALUES[t[0].piece_type])  # the king first, then by value
            names = [f"the {PIECE_NAMES[piece.piece_type]} on {sq}" for piece, sq in targets]
            return f"forks {' and '.join(names)}"
        if m.subskill == "hanging_pieces":
            piece = chess.Piece.from_symbol(m.details["captured"])
            return f"wins the undefended {PIECE_NAMES[piece.piece_type]} on {m.details['square']}"
    return None


def explain(
    *,
    fen_before: str,
    played_uci: str,
    best_line: list[str],
    reply_line: list[str],
    before: Evaluation | None,
    after: Evaluation | None,
    transition: MateTransition,
    actor: Actor,
    is_mistake: bool,
) -> list[str]:
    """Reasons for one move. `before`/`after` are from the MOVER's side; `best_line` starts
    from `fen_before`; `reply_line` is the engine's best continuation after the played move."""
    board = chess.Board(fen_before)
    mover = board.turn
    played = chess.Move.from_uci(played_uci)
    if played not in board.legal_moves:
        return []
    played_san = board.san(played)
    after_board = board.copy()
    after_board.push(played)

    if after_board.is_checkmate():
        return [f"{played_san} is checkmate."]
    if not is_mistake:
        return []

    reasons: list[str] = []
    best_san, best_end = _san_line(board, best_line, LINE_PLIES)
    reply_san, reply_end = _san_line(after_board, reply_line, LINE_PLIES)
    best = best_san[0] if best_san else None

    # 1. Forced mates.
    if transition in (MateTransition.ALLOWED_MATE, MateTransition.MATE_TO_MATED) and after:
        line = " ".join(reply_san)
        reasons.append(
            f"After {played_san}, {actor.other} {'has' if actor.other != 'you' else 'have'} "
            f"a forced mate in {abs(after.mate)}" + (f": {line}." if line else ".")
        )
    if transition in (MateTransition.MISSED_MATE, MateTransition.MATE_TO_MATED) and before and best:
        reasons.append(f"{best} would have forced mate in {before.mate}: {' '.join(best_san)}.")
    if reasons:
        return reasons

    # 2. Material along the engine's lines.
    played_net, played_text = material_outcome(board, reply_end, mover) if reply_san else (0, "")
    best_net, best_text = material_outcome(board, best_end, mover) if best_san else (0, "")
    if reply_san and played_net <= -1 and played_net < best_net and played_text:
        reasons.append(
            f"After {played_san}, the best reply is {' '.join(reply_san)}: "
            f"{actor.name} {actor.verb('lose')} {played_text}."
        )
    if best and best_net >= 1 and best_net > played_net and best_text:
        reasons.append(f"{best} wins {best_text}: {' '.join(best_san)}.")

    # 3. Verified motifs in the better move and in the reply.
    if best:
        text = _motif_text(board, chess.Move.from_uci(best_line[0]))
        if text:
            reasons.append(f"{best} {text}.")
    if reply_san:
        text = _motif_text(after_board, chess.Move.from_uci(reply_line[0]))
        if text:
            reasons.append(
                f"Your move allowed {reply_san[0]}, which {text}."
                if actor is YOU
                else f"It allowed {reply_san[0]}, which {text}."
            )

    # 4. Nothing concrete: say so, with the engine's margin.
    if not reasons and best:
        margin = (
            f" by about {abs(before.cp - after.cp) / 100:.1f} pawns"
            if before and after and before.cp is not None and after.cp is not None
            else ""
        )
        reasons.append(
            f"No material changes hands right away; the engine prefers {best}{margin}. "
            f"The difference is positional (piece activity, king safety or pawn "
            f"structure): {' '.join(best_san[:6])}."
        )
    return reasons
