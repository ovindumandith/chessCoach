from types import SimpleNamespace

import chess

from chesscoach.analysis.scores import Evaluation, MateTransition
from chesscoach.annotation.explain import OPPONENT, YOU, explain, material_outcome
from chesscoach.annotation.service import _opponent_entry, verdict_kind

AFTER_1E4_D5 = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2"
SCHOLAR_BEFORE_MATE = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
LEGAL_BEFORE_BXD1 = "rn1qkbnr/ppp2p1p/3p2p1/4N3/2B1P1b1/2N5/PPPP1PPP/R1BQK2R b KQkq - 0 5"
KNIGHT_FORK = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"


def run(**kw):
    defaults = dict(
        before=Evaluation(cp=0),
        after=Evaluation(cp=-500),
        reply_line=[],
        best_line=[],
        transition=MateTransition.NONE,
        actor=YOU,
        is_mistake=True,
    )
    return explain(**{**defaults, **kw})


def test_hanging_queen_explained_by_material_and_motif():
    reasons = run(
        fen_before=AFTER_1E4_D5, played_uci="d1g4", reply_line=["c8g4"], best_line=["e4d5", "d8d5"]
    )
    assert "After Qg4, the best reply is Bxg4: you lose a queen." in reasons
    assert "Your move allowed Bxg4, which wins the undefended queen on g4." in reasons


def test_opponent_wording():
    reasons = run(
        fen_before=AFTER_1E4_D5,
        played_uci="d1g4",
        reply_line=["c8g4"],
        best_line=["e4d5", "d8d5"],
        actor=OPPONENT,
    )
    assert "After Qg4, the best reply is Bxg4: your opponent loses a queen." in reasons
    assert "It allowed Bxg4, which wins the undefended queen on g4." in reasons


def test_missed_mate():
    reasons = run(
        fen_before=SCHOLAR_BEFORE_MATE,
        played_uci="h5e2",
        best_line=["h5f7"],
        before=Evaluation(mate=1),
        after=Evaluation(cp=-200),
        transition=MateTransition.MISSED_MATE,
    )
    assert reasons == ["Qxf7# would have forced mate in 1: Qxf7#."]


def test_allowed_mate():
    reasons = run(
        fen_before=LEGAL_BEFORE_BXD1,
        played_uci="g4d1",
        reply_line=["c4f7", "e8e7", "c3d5"],
        before=Evaluation(cp=-200),
        after=Evaluation(mate=-2),
        transition=MateTransition.ALLOWED_MATE,
    )
    assert reasons == ["After Bxd1, your opponent has a forced mate in 2: Bxf7+ Ke7 Nd5#."]


def test_checkmate_is_named_even_when_not_a_mistake():
    assert run(fen_before=SCHOLAR_BEFORE_MATE, played_uci="h5f7", is_mistake=False) == [
        "Qxf7# is checkmate."
    ]


def test_fork_in_the_better_move():
    reasons = run(fen_before=KNIGHT_FORK, played_uci="e1e2", best_line=["b5c7"])
    assert "Nc7+ forks the king on e8 and the rook on a8." in reasons


def test_positional_fallback_never_invents_tactics():
    start = chess.Board().fen()
    reasons = run(
        fen_before=start,
        played_uci="g1h3",
        best_line=["e2e4", "e7e5"],
        before=Evaluation(cp=30),
        after=Evaluation(cp=-40),
    )
    assert len(reasons) == 1
    assert reasons[0].startswith(
        "No material changes hands right away; the engine prefers e4 by about 0.7 pawns."
    )


def test_good_moves_get_no_lecture():
    assert run(fen_before=chess.Board().fen(), played_uci="e2e4", is_mistake=False) == []


def test_illegal_move_gives_nothing():
    assert run(fen_before=chess.Board().fen(), played_uci="e2e5") == []


def test_material_outcome_phrase():
    start = chess.Board(AFTER_1E4_D5)
    end = start.copy()
    for u in ("d1g4", "c8g4", "e4d5"):
        end.push_uci(u)
    assert material_outcome(start, end, chess.WHITE) == (-8, "a queen for a pawn")


def test_verdict_kind_thresholds():
    assert verdict_kind(0.2, MateTransition.NONE, False) == "blunder"
    assert verdict_kind(0.12, MateTransition.NONE, False) == "mistake"
    assert verdict_kind(0.06, MateTransition.NONE, False) == "inaccuracy"
    assert verdict_kind(0.01, MateTransition.NONE, False) == "good"
    assert verdict_kind(0.0, MateTransition.NONE, True) == "best"
    assert verdict_kind(0.0, MateTransition.MISSED_MATE, False) == "blunder"


def ma(**kw):
    defaults = dict(
        eval_after_cp=None,
        eval_after_mate=None,
        eval_before_cp=None,
        eval_before_mate=None,
        features={},
        principal_variation=[],
    )
    return SimpleNamespace(**{**defaults, **kw})


def test_opponent_blunder_graded_from_surrounding_student_analysis():
    # Student is Black. 1.e4 e5 2.Qh5 Nc6, then White blunders 3.Qxe5+?? Nxe5.
    board = chess.Board()
    for u in ("e2e4", "e7e5", "d1h5", "b8c6"):
        board.push_uci(u)
    prev = ma(
        eval_after_cp=-20,
        features={"refutation_pv": ["f1c4", "g7g6"], "refutation_san": ["Bc4", "g6"]},
    )  # Black's side
    nxt = ma(eval_before_cp=850, principal_variation=["c6e5", "d2d4"])  # Black up a queen
    e = _opponent_entry(5, board, chess.Move.from_uci("h5e5"), prev, nxt)
    assert (e["side"], e["san"], e["verdict"], e["label"]) == (
        "opponent",
        "Qxe5+",
        "blunder",
        "Blunder",
    )
    # White's point of view: before about +0.20 for White, after -8.50 (Black winning).
    assert e["eval_before"] == {"cp": 20, "mate": None}
    assert e["eval_after"] == {"cp": -850, "mate": None}
    assert e["best_move_san"] == "Bc4"
    assert (
        "After Qxe5+, the best reply is Nxe5 d4: your opponent loses a queen for a pawn."
        in e["reasons"]
    )


def test_opponent_best_move_and_last_move_without_followup():
    board = chess.Board()
    board.push_uci("e2e4")
    prev = ma(eval_after_cp=-30, features={"refutation_pv": ["e7e5"], "refutation_san": ["e5"]})
    nxt = ma(eval_before_cp=-28, principal_variation=["g1f3"])
    best = _opponent_entry(2, board, chess.Move.from_uci("e7e5"), prev, nxt)
    assert best["verdict"] == "best" and best["reasons"] == []
    assert _opponent_entry(2, board, chess.Move.from_uci("e7e5"), prev, None) is None


def _boards(fen, ucis):
    start = chess.Board(fen)
    end = start.copy()
    for u in ucis:
        end.push(chess.Move.from_uci(u))
    return start, end


def test_trades_are_netted_like_a_player_would_say_them():
    from collections import Counter

    from chesscoach.annotation.explain import _net_trades

    lost = Counter({chess.ROOK: 1, chess.BISHOP: 1, chess.KNIGHT: 1})
    won = Counter({chess.ROOK: 1, chess.BISHOP: 1, chess.PAWN: 1})
    assert _net_trades(lost, won) == (Counter({chess.KNIGHT: 1}), Counter({chess.PAWN: 1}), False)
    # a knight and a pawn for a bishop -> just a pawn
    assert _net_trades(Counter({chess.BISHOP: 1}), Counter({chess.KNIGHT: 1, chess.PAWN: 1})) == (
        Counter(),
        Counter({chess.PAWN: 1}),
        False,
    )
    # a rook for a bishop -> the exchange
    assert _net_trades(Counter({chess.ROOK: 1}), Counter({chess.BISHOP: 1})) == (
        Counter(),
        Counter(),
        True,
    )


def test_losing_the_exchange_is_named():
    # Black's bishop takes the rook on a1 and the knight recaptures: White lost the exchange.
    start, end = _boards("4k3/8/8/8/8/8/1b6/R1N1K3 b - - 0 1", ["b2a1", "c1b3", "e8d7", "b3a1"])
    assert material_outcome(start, end, chess.WHITE) == (-2, "the exchange")
