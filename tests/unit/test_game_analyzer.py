import pytest

from chesscoach.analysis.game_analyzer import AnalysisSettings, analyze_game
from chesscoach.analysis.scores import MateTransition
from chesscoach.db.enums import Color, GamePhase
from tests.fakes import FakeAnalyzer

SETTINGS = AnalysisSettings(depth=8, multipv=2, critical_wp_loss=0.10)

SCHOLARS_MATE = """[White "Ovindu"]
[Black "Opp"]

1. e4 { [%clk 0:09:58] } e5 { [%clk 0:09:57] } 2. Bc4 { [%clk 0:09:50] } Nc6 { [%clk 0:09:40] }
3. Qh5 { [%clk 0:09:30] } Nf6 { [%clk 0:09:00] } 4. Qxf7# { [%clk 0:09:20] } 1-0
"""

MISSED_MATE = """[White "Ovindu"]
[Black "Opp"]

1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qe2 *
"""


def run(pgn, color, **kw):
    return analyze_game(pgn, color, FakeAnalyzer(), SETTINGS, game_key="g", **kw)


def test_only_student_moves_are_recorded_with_plies():
    assert [r.ply for r in run(SCHOLARS_MATE, Color.WHITE)] == [1, 3, 5, 7]
    assert [r.ply for r in run(SCHOLARS_MATE, Color.BLACK)] == [2, 4, 6]


def test_record_contents_and_clocks():
    records = run(SCHOLARS_MATE, Color.WHITE)
    first, second = records[0], records[1]
    assert first.uci_move == "e2e4" and first.san_move == "e4"
    assert first.fen_before.startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")
    assert first.phase == GamePhase.OPENING
    assert first.clock_before_ms is None  # no earlier student clock
    assert first.clock_after_ms == 598_000
    assert second.clock_before_ms == 598_000
    assert second.clock_after_ms == 590_000


def test_delivered_checkmate_is_terminal_mate_zero():
    last = run(SCHOLARS_MATE, Color.WHITE)[-1]
    assert last.san_move == "Qxf7#"
    assert last.eval_before.mate == 1
    assert last.eval_after.mate == 0
    assert last.features["played_best"] is True
    assert last.features["terminal"] == "checkmate"
    assert last.win_prob_loss == 0.0
    assert not last.critical


def test_missed_mate_in_one_is_critical_without_cp_loss():
    last = run(MISSED_MATE, Color.WHITE)[-1]
    assert last.san_move == "Qe2"
    assert last.best_move_uci == "h5f7"
    assert last.transition == MateTransition.MISSED_MATE
    assert last.cp_loss is None  # mate vs centipawn: not comparable
    assert last.critical
    assert last.features["pv_san"] == ["Qxf7#"]


def test_multipv_second_best_and_gap():
    last = run(MISSED_MATE, Color.WHITE)[-1]
    assert last.second_best is not None and last.second_best.cp is not None
    assert last.features["only_move_gap_wp"] > 0


def test_only_plies_filter():
    records = run(SCHOLARS_MATE, Color.WHITE, only_plies={5, 7})
    assert [r.ply for r in records] == [5, 7]
    # Clock bookkeeping still follows skipped student moves.
    assert records[0].clock_before_ms == 590_000


def test_black_perspective_is_normalized():
    # After 3...Nf6 White threatens mate; from Black's view that position is lost.
    records = run(SCHOLARS_MATE, Color.BLACK)
    nf6 = records[-1]
    assert nf6.san_move == "Nf6"
    assert nf6.eval_after.mate == -1
    assert nf6.transition == MateTransition.ALLOWED_MATE
    assert nf6.critical


def test_unparseable_pgn_raises():
    with pytest.raises(ValueError):
        run("1. e4 e5 2. Qh8 *", Color.WHITE)
