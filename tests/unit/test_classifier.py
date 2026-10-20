import pytest

from chesscoach.analysis.scores import Evaluation
from chesscoach.classification.classifier import (
    GameContext,
    MoveEvidence,
    classify_move,
    parse_base_time,
    severity_band,
)
from chesscoach.classification.taxonomy import get_taxonomy
from chesscoach.db.enums import EvidenceType, GamePhase, OpportunityOutcome

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
KNIGHT_FORK = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"
ROOK_ENDING = "8/5pk1/6p1/8/8/6P1/r4PK1/R7 w - - 0 40"
NO_CTX = GameContext()


def ev(**kw):
    defaults = dict(
        fen_before=START,
        fen_after=START,
        uci_move="g1f3",
        phase=GamePhase.MIDDLEGAME,
        eval_before=Evaluation(cp=0),
        best_move_uci="e2e4",
        win_prob_loss=0.0,
        features={
            "legal_moves": 20,
            "played_best": False,
            "mate_transition": "none",
            "only_move_gap_wp": 0.01,
            "refutation_pv": [],
        },
    )
    features = {**defaults["features"], **kw.pop("features", {})}
    return MoveEvidence(**{**defaults, **kw, "features": features})


def kinds(result):
    return [(o.evidence_type, o.skill_code, o.subskill_code) for o in result.observations]


def test_every_auto_code_is_in_taxonomy():
    taxonomy = get_taxonomy()
    for code, cat in taxonomy.categories.items():
        for sub, spec in cat.subskills.items():
            if spec.auto:
                assert taxonomy.is_valid(code, sub)


@pytest.mark.parametrize(
    ("loss", "band"), [(0.01, None), (0.06, "inaccuracy"), (0.12, "mistake"), (0.4, "blunder")]
)
def test_severity_bands(loss, band):
    assert severity_band(loss) == band


def test_forced_move_is_never_classified():
    result = classify_move(ev(win_prob_loss=0.5, features={"legal_moves": 1}), NO_CTX)
    assert result.observations == [] and result.opportunities == []


def test_good_move_produces_nothing():
    assert kinds(classify_move(ev(win_prob_loss=0.01), NO_CTX)) == []


def test_unexplained_error_stays_unclassified():
    result = classify_move(ev(win_prob_loss=0.12), NO_CTX)
    assert kinds(result) == [(EvidenceType.MOVE_QUALITY, "unclassified", None)]
    assert result.observations[0].confidence is None
    assert result.observations[0].details["band"] == "mistake"


def test_missed_fork_needed_and_costly():
    m = ev(
        fen_before=KNIGHT_FORK,
        best_move_uci="b5c7",
        uci_move="b5d4",
        win_prob_loss=0.4,
        features={"only_move_gap_wp": 0.4},
    )
    result = classify_move(m, NO_CTX)
    assert (EvidenceType.MOTIF, "tactical_awareness", "forks") in kinds(result)
    assert [(o.subskill_code, o.outcome) for o in result.opportunities] == [
        ("forks", OpportunityOutcome.MISSED)
    ]
    assert not any(k[0] == EvidenceType.MOVE_QUALITY for k in kinds(result))


def test_found_fork_is_a_converted_opportunity():
    m = ev(
        fen_before=KNIGHT_FORK,
        best_move_uci="b5c7",
        uci_move="b5c7",
        win_prob_loss=0.0,
        features={"only_move_gap_wp": 0.4, "played_best": True},
    )
    result = classify_move(m, NO_CTX)
    assert result.observations == []
    assert result.opportunities[0].outcome == OpportunityOutcome.CONVERTED


def test_unneeded_fork_is_not_an_opportunity():
    # The fork was available but the engine says other moves were nearly as good.
    m = ev(
        fen_before=KNIGHT_FORK,
        best_move_uci="b5c7",
        uci_move="b5d4",
        win_prob_loss=0.02,
        features={"only_move_gap_wp": 0.01},
    )
    result = classify_move(m, NO_CTX)
    assert result.opportunities == [] and result.observations == []


def test_missed_mate_recorded_even_when_still_winning():
    m = ev(
        eval_before=Evaluation(mate=2),
        win_prob_loss=0.0,
        features={"mate_transition": "missed_mate"},
    )
    result = classify_move(m, NO_CTX)
    assert kinds(result) == [(EvidenceType.MOTIF, "tactical_awareness", "mating_patterns")]
    assert result.opportunities[0].outcome == OpportunityOutcome.MISSED


def test_allowed_mate_adds_motif_and_defensive_inference():
    result = classify_move(
        ev(win_prob_loss=0.5, features={"mate_transition": "allowed_mate"}), NO_CTX
    )
    assert (EvidenceType.MOTIF, "tactical_awareness", "mating_patterns") in kinds(result)
    assert (EvidenceType.SKILL_INFERENCE, "defensive_skills", "threat_prevention") in kinds(result)


def test_allowed_fork_from_refutation():
    m = ev(
        fen_after="4k3/8/8/8/1n6/8/8/R3K3 b - - 0 1",
        win_prob_loss=0.3,
        features={"refutation_pv": ["b4c2"]},
    )
    assert (EvidenceType.MOTIF, "tactical_awareness", "forks") in kinds(classify_move(m, NO_CTX))


def test_endgame_error_infers_rook_endgame_with_low_confidence():
    m = ev(fen_before=ROOK_ENDING, phase=GamePhase.ENDGAME, best_move_uci="g2f3", win_prob_loss=0.2)
    result = classify_move(m, NO_CTX)
    assert kinds(result) == [(EvidenceType.SKILL_INFERENCE, "endgame_technique", "rook_endgames")]
    assert result.observations[0].confidence == 0.3


def test_error_while_winning_is_conversion():
    result = classify_move(ev(eval_before=Evaluation(cp=600), win_prob_loss=0.2), NO_CTX)
    assert (
        EvidenceType.SKILL_INFERENCE,
        "winning_position_conversion",
        "preserving_advantage",
    ) in kinds(result)


def test_missed_only_move_is_defensive_resource():
    m = ev(eval_before=Evaluation(cp=-50), win_prob_loss=0.25, features={"only_move_gap_wp": 0.45})
    assert (EvidenceType.SKILL_INFERENCE, "defensive_skills", "finding_resources") in kinds(
        classify_move(m, NO_CTX)
    )


def test_time_trouble_needs_a_clock():
    with_clock = classify_move(ev(win_prob_loss=0.06, clock_before_ms=25_000), NO_CTX)
    assert (EvidenceType.SKILL_INFERENCE, "practical_play", "time_management") in kinds(with_clock)
    without = classify_move(ev(win_prob_loss=0.06), NO_CTX)
    assert kinds(without) == [(EvidenceType.MOVE_QUALITY, "unclassified", None)]


def test_time_trouble_relative_to_base_time():
    m = ev(win_prob_loss=0.06, clock_before_ms=100_000)  # 100s left
    assert (
        classify_move(m, GameContext(base_time_seconds=1800)).observations[0].subskill_code
        == "time_management"
    )
    assert (
        classify_move(m, GameContext(base_time_seconds=600)).observations[0].skill_code
        == "unclassified"
    )


@pytest.mark.parametrize(
    ("tc", "base"),
    [("600+5", 600), ("300", 300), ("-", None), (None, None), ("40/7200:3600", None)],
)
def test_parse_base_time(tc, base):
    assert parse_base_time(tc) == base
