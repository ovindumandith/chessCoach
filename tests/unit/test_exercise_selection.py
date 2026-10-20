import pytest

from chesscoach.analysis.scores import Evaluation
from chesscoach.exercises.selection import (
    PositionInput,
    build_candidate,
    is_exercisable,
    parse_move,
    relevant,
    unique_solution,
)

BACK_RANK = "6k1/5ppp/8/8/8/8/8/R3R1K1 w - - 0 1"  # Ra8# and Re8# both mate
KNIGHT_FORK = "r3k3/8/8/1N6/8/8/8/4K3 w - - 0 1"
ROOK_ENDING = "8/5pk1/6p1/8/8/6P1/r4PK1/R7 w - - 0 40"


def pos(
    fen=BACK_RANK,
    best="a1a8",
    mate=1,
    cp=None,
    gap=None,
    phase="middlegame",
    legal=None,
    line=("Ra8#",),
):
    ev = Evaluation(mate=mate) if mate is not None else Evaluation(cp=cp)
    return PositionInput(
        move_analysis_id="m1",
        game_id="g1",
        ply=21,
        fen=fen,
        phase=phase,
        played_uci="g1f1",
        played_san="Kf1",
        best_uci=best,
        eval_before=ev,
        eval_after_text="+0.50",
        gap=gap,
        legal_moves=legal,
        best_line_san=list(line),
    )


def test_mate_in_one_accepts_every_mating_move():
    c = build_candidate(pos(), "mating_patterns")
    assert sorted(c.accepted_moves) == ["a1a8", "e1e8"]
    assert c.difficulty == "easy"
    assert c.hints[0] == "There is a forced checkmate."
    assert c.hints[1:] == ["Use your rook.", "The rook on a1."]
    assert "Ra8#" in c.explanation
    assert c.details["game_move"]["san"] == "Kf1"


@pytest.mark.parametrize("gap, ok", [(0.5, True), (0.15, True), (0.14, False), (None, False)])
def test_unique_solution_needs_a_clear_margin(gap, ok):
    p = pos(fen=KNIGHT_FORK, best="b5c7", mate=None, cp=300, gap=gap)
    assert unique_solution(p) is ok
    assert (build_candidate(p, "forks") is not None) is ok


def test_difficulty_from_margin_and_mate_distance():
    assert (
        build_candidate(
            pos(fen=KNIGHT_FORK, best="b5c7", mate=None, cp=300, gap=0.45), "forks"
        ).difficulty
        == "easy"
    )
    assert (
        build_candidate(
            pos(fen=KNIGHT_FORK, best="b5c7", mate=None, cp=300, gap=0.2), "forks"
        ).difficulty
        == "hard"
    )
    assert build_candidate(pos(mate=3), "mating_patterns").difficulty == "hard"


def test_rejects_illegal_missing_or_trivial():
    assert build_candidate(pos(best="a1a2"), "mating_patterns").accepted_moves  # legal, fine
    assert build_candidate(pos(best="h1h8"), "mating_patterns") is None  # no piece on h1
    assert build_candidate(pos(best=None), "mating_patterns") is None
    assert build_candidate(pos(legal=2), "mating_patterns") is None


def test_relevance_by_skill():
    fork = pos(fen=KNIGHT_FORK, best="b5c7", mate=None, cp=300, gap=0.4)
    assert relevant(fork, "tactical_awareness", "forks", labelled=False)
    assert not relevant(fork, "tactical_awareness", "mating_patterns", labelled=False)
    ending = pos(fen=ROOK_ENDING, best="g2f3", mate=None, cp=0, gap=0.3, phase="endgame")
    assert relevant(ending, "endgame_technique", "rook_endgames", labelled=False)
    assert not relevant(ending, "endgame_technique", "pawn_endgames", labelled=False)
    # Coach-labelled skills are relevant wherever an observation names them.
    assert relevant(fork, "calculation", "forcing_variations", labelled=True)


def test_not_every_skill_is_a_board_exercise():
    assert not is_exercisable("practical_play", "time_management")
    assert not is_exercisable("unclassified", None)
    assert is_exercisable("tactical_awareness", "forks")


@pytest.mark.parametrize(
    "text, uci",
    [
        ("a1a8", "a1a8"),
        ("Ra8#", "a1a8"),
        ("Ra8", "a1a8"),
        ("Re8", "e1e8"),
        ("a1h1", None),
        ("Qd8", None),
        ("nonsense", None),
    ],
)
def test_parse_move_accepts_uci_and_san_only_if_legal(text, uci):
    move = parse_move(BACK_RANK, text)
    assert (move.uci() if move else None) == uci


def test_defensive_position_gets_a_defensive_hint():
    # Legal's Mate before ...Bxd1: the student (Black) has no mate; the task is to avoid
    # walking into one, so "there is a forced checkmate" would be a misleading hint.
    legal = "rn1qkbnr/ppp2p1p/3p2p1/4N3/2B1P1b1/2N5/PPPP1PPP/R1BQK2R b KQkq - 0 5"
    p = pos(fen=legal, best="d6e5", mate=None, cp=-150, gap=0.4, line=("dxe5",))
    c = build_candidate(p, "mating_patterns")
    assert "threat" in c.hints[0] and "checkmate" not in c.hints[0]
    assert build_candidate(pos(), "mating_patterns").hints[0] == "There is a forced checkmate."
