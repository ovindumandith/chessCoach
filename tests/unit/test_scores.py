import chess
import chess.engine
import pytest

from chesscoach.analysis.scores import (
    Evaluation,
    MateTransition,
    from_pov_score,
    is_critical,
    mate_transition,
    move_loss,
    win_probability,
)


def pov(score, color):
    return chess.engine.PovScore(score, color)


class TestPerspective:
    def test_white_relative_score_for_black_student_is_negated(self):
        # Engine reports +150 for White (side to move); the student is Black.
        ev = from_pov_score(pov(chess.engine.Cp(150), chess.WHITE), chess.BLACK)
        assert ev == Evaluation(cp=-150)

    def test_same_side_is_unchanged(self):
        assert from_pov_score(pov(chess.engine.Cp(-40), chess.BLACK), chess.BLACK).cp == -40

    def test_mate_sign_follows_student(self):
        # Black to move and Black mates in 2 -> student White is getting mated in 2.
        ev = from_pov_score(pov(chess.engine.Mate(2), chess.BLACK), chess.WHITE)
        assert ev == Evaluation(mate=-2)
        assert ev.cp is None  # never converted to centipawns


def test_evaluation_requires_exactly_one_value():
    with pytest.raises(ValueError):
        Evaluation()
    with pytest.raises(ValueError):
        Evaluation(cp=10, mate=1)


class TestWinProbability:
    def test_equal_is_half(self):
        assert win_probability(Evaluation(cp=0)) == pytest.approx(0.5)

    def test_monotonic_and_symmetric(self):
        a, b = win_probability(Evaluation(cp=300)), win_probability(Evaluation(cp=-300))
        assert a > 0.5 > b
        assert a + b == pytest.approx(1.0)

    def test_mates_are_extremes(self):
        assert win_probability(Evaluation(mate=3)) == 1.0
        assert win_probability(Evaluation(mate=0)) == 1.0  # delivered checkmate
        assert win_probability(Evaluation(mate=-1)) == 0.0


class TestMoveLoss:
    def test_centipawn_loss_when_both_cp(self):
        loss = move_loss(Evaluation(cp=120), Evaluation(cp=-180))
        assert loss.cp_loss == 300
        assert loss.win_prob_loss > 0.2
        assert loss.transition == MateTransition.NONE

    def test_improvement_is_zero_loss(self):
        loss = move_loss(Evaluation(cp=0), Evaluation(cp=50))
        assert loss.cp_loss == 0
        assert loss.win_prob_loss == 0.0

    def test_no_cp_loss_across_mate_scores(self):
        loss = move_loss(Evaluation(mate=2), Evaluation(cp=400))
        assert loss.cp_loss is None
        assert loss.transition == MateTransition.MISSED_MATE

    def test_played_best_is_zero_even_with_search_noise(self):
        loss = move_loss(Evaluation(cp=80), Evaluation(cp=55), played_best=True)
        assert (loss.cp_loss, loss.win_prob_loss) == (0, 0.0)

    def test_winning_position_loss_is_small_in_win_probability(self):
        # +900 -> +600 is 300cp but practically still winning.
        big_edge = move_loss(Evaluation(cp=900), Evaluation(cp=600))
        equal = move_loss(Evaluation(cp=0), Evaluation(cp=-300))
        assert big_edge.cp_loss == equal.cp_loss == 300
        assert big_edge.win_prob_loss < equal.win_prob_loss / 3


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (Evaluation(cp=10), Evaluation(cp=-10), MateTransition.NONE),
        (Evaluation(mate=3), Evaluation(cp=500), MateTransition.MISSED_MATE),
        (Evaluation(mate=3), Evaluation(mate=-2), MateTransition.MATE_TO_MATED),
        (Evaluation(mate=3), Evaluation(mate=5), MateTransition.STILL_MATING),
        (Evaluation(mate=1), Evaluation(mate=0), MateTransition.STILL_MATING),
        (Evaluation(cp=50), Evaluation(mate=-1), MateTransition.ALLOWED_MATE),
        (Evaluation(cp=50), Evaluation(mate=4), MateTransition.FOUND_MATE),
        (Evaluation(mate=-3), Evaluation(mate=-2), MateTransition.STILL_MATED),
        (Evaluation(mate=-3), Evaluation(cp=-800), MateTransition.ESCAPED_MATE),
    ],
)
def test_mate_transitions(before, after, expected):
    assert mate_transition(before, after) == expected


def test_critical_by_threshold_or_serious_transition():
    small = move_loss(Evaluation(cp=20), Evaluation(cp=0))
    blunder = move_loss(Evaluation(cp=0), Evaluation(cp=-400))
    missed = move_loss(Evaluation(mate=4), Evaluation(cp=2000))  # still winning, but missed mate
    assert not is_critical(small, 0.10)
    assert is_critical(blunder, 0.10)
    assert is_critical(missed, 0.10)
