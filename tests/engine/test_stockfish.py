"""Known-position checks against a real Stockfish binary. Run with `pytest -m engine`.

Skipped automatically when STOCKFISH_PATH does not point to an executable.
"""

from pathlib import Path

import pytest

from chesscoach.analysis.engine import EngineConfig, StockfishAnalyzer
from chesscoach.analysis.game_analyzer import AnalysisSettings, analyze_game
from chesscoach.analysis.scores import MateTransition
from chesscoach.core.config import Settings
from chesscoach.db.enums import Color

pytestmark = pytest.mark.engine

SETTINGS = AnalysisSettings(depth=12, multipv=2, critical_wp_loss=0.10)


@pytest.fixture(scope="module")
def analyzer():
    path = Settings().stockfish_path
    if not Path(path).is_file():
        pytest.skip(f"Stockfish not available at {path!r}")
    with StockfishAnalyzer(EngineConfig(path=path, depth=12, threads=1, hash_mb=64)) as a:
        yield a


def test_identity_is_recorded(analyzer):
    assert analyzer.identity.name == "Stockfish"
    assert analyzer.identity.version
    assert len(analyzer.identity.checksum) == 64


def test_finds_and_records_delivered_mate(analyzer):
    pgn = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0"
    last = analyze_game(pgn, Color.WHITE, analyzer, SETTINGS, game_key="m1")[-1]
    assert last.best_move_uci == "h5f7"
    assert last.eval_before.mate == 1
    assert last.eval_after.mate == 0
    assert last.win_prob_loss == 0.0


def test_missed_mate_is_flagged(analyzer):
    pgn = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qe2 *"
    last = analyze_game(pgn, Color.WHITE, analyzer, SETTINGS, game_key="m2")[-1]
    assert last.transition == MateTransition.MISSED_MATE
    assert last.cp_loss is None
    assert last.critical


def test_hanging_queen_from_both_perspectives(analyzer):
    pgn = "1. e4 d5 2. Qg4 Bxg4 *"
    white = analyze_game(pgn, Color.WHITE, analyzer, SETTINGS, game_key="q1")
    qg4 = white[-1]
    assert qg4.san_move == "Qg4"
    assert qg4.cp_loss is not None and qg4.cp_loss > 500
    assert qg4.eval_after.cp < -500  # White's view: losing
    assert qg4.critical

    black = analyze_game(pgn, Color.BLACK, analyzer, SETTINGS, game_key="q2")
    bxg4 = black[-1]
    assert bxg4.san_move == "Bxg4"
    assert bxg4.eval_after.cp > 500  # Black's view: winning
    assert bxg4.win_prob_loss < 0.05
    assert not bxg4.critical


def test_pv_is_legal_and_rendered(analyzer):
    records = analyze_game("1. e4 e5 2. Nf3 Nc6 *", Color.WHITE, analyzer, SETTINGS, game_key="pv")
    for r in records:
        assert r.principal_variation
        assert r.features["pv_san"]
        assert len(r.features["pv_san"]) <= len(r.principal_variation)
