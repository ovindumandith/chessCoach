"""Evaluation normalization and move-loss rules. Pure functions, no engine I/O.

Conventions (all values from the STUDENT's point of view):
- `cp` is centipawns, positive = good for the student.
- `mate` is signed moves-to-mate: +3 = the student mates in 3; -2 = the student gets mated in 2.
- After a student move that delivers checkmate, the position is terminal and is stored as
  mate = 0. (A student can never be checkmated by their own move, so 0 is unambiguous here.)
- Exactly one of `cp` / `mate` is set for a known evaluation.

Mate scores are never converted to centipawns. Centipawn loss is only computed when both
evaluations are ordinary centipawn values; otherwise the comparison uses win probability
and an explicit mate-transition label.
"""

import math
from dataclasses import dataclass
from enum import StrEnum

import chess
import chess.engine

SCORES_VERSION = "scores-v1"

# Lichess's published win-probability model (lila `WinPercent`), expressed in [0, 1].
WIN_PROB_K = 0.00368208


class MateTransition(StrEnum):
    NONE = "none"
    MISSED_MATE = "missed_mate"  # had a forced mate, no longer does (but not losing to mate)
    MATE_TO_MATED = "mate_to_mated"  # had a forced mate, now gets mated
    ALLOWED_MATE = "allowed_mate"  # no mate on board, now gets mated
    STILL_MATING = "still_mating"  # had a mate, still has one (maybe slower)
    STILL_MATED = "still_mated"  # was getting mated, still is
    FOUND_MATE = "found_mate"  # no mate before, now has one (rare; search horizon)
    ESCAPED_MATE = (
        "escaped_mate"  # was getting mated, no longer (opponent's earlier error / horizon)
    )


@dataclass(frozen=True)
class Evaluation:
    cp: int | None = None
    mate: int | None = None

    def __post_init__(self):
        if (self.cp is None) == (self.mate is None):
            raise ValueError("Evaluation needs exactly one of cp or mate")

    @property
    def is_mate(self) -> bool:
        return self.mate is not None


def from_pov_score(score: chess.engine.PovScore, student_color: chess.Color) -> Evaluation:
    """Normalize an engine score to the student's point of view."""
    relative = score.pov(student_color)
    mate = relative.mate()
    if mate is not None:
        return Evaluation(mate=mate)
    cp = relative.score()
    if cp is None:  # pragma: no cover - python-chess always yields cp or mate
        raise ValueError(f"Engine score has neither cp nor mate: {score}")
    return Evaluation(cp=cp)


def checkmate_delivered() -> Evaluation:
    return Evaluation(mate=0)


def win_probability(ev: Evaluation) -> float:
    """Probability-like score in [0, 1] for the student. Mates map to the extremes."""
    if ev.mate is not None:
        return 1.0 if ev.mate >= 0 else 0.0
    return 1.0 / (1.0 + math.exp(-WIN_PROB_K * ev.cp))


def mate_transition(before: Evaluation, after: Evaluation) -> MateTransition:
    b, a = before.mate, after.mate
    if b is None and a is None:
        return MateTransition.NONE
    if b is not None and b > 0:
        if a is None:
            return MateTransition.MISSED_MATE
        return MateTransition.STILL_MATING if a >= 0 else MateTransition.MATE_TO_MATED
    if b is not None and b < 0:
        if a is None or a >= 0:
            return MateTransition.ESCAPED_MATE
        return MateTransition.STILL_MATED
    # b is None (centipawn before) and a is a mate
    return MateTransition.FOUND_MATE if a >= 0 else MateTransition.ALLOWED_MATE


@dataclass(frozen=True)
class MoveLoss:
    cp_loss: int | None  # only when both evaluations are centipawn values
    win_prob_loss: float  # always defined, clamped at 0
    transition: MateTransition


def move_loss(before: Evaluation, after: Evaluation, *, played_best: bool = False) -> MoveLoss:
    """Loss of the played move relative to the engine's best line.

    If the student played the engine's top move, loss is defined as zero: any difference
    between the two searches is search noise, not a decision error. The raw evaluations
    are still stored separately so instability can be studied.
    """
    transition = mate_transition(before, after)
    if played_best:
        return MoveLoss(
            cp_loss=0 if transition == MateTransition.NONE else None,
            win_prob_loss=0.0,
            transition=transition,
        )
    cp_loss = None
    if before.cp is not None and after.cp is not None:
        cp_loss = max(0, before.cp - after.cp)
    wp_loss = max(0.0, win_probability(before) - win_probability(after))
    return MoveLoss(cp_loss=cp_loss, win_prob_loss=round(wp_loss, 6), transition=transition)


SERIOUS_TRANSITIONS = {
    MateTransition.MISSED_MATE,
    MateTransition.MATE_TO_MATED,
    MateTransition.ALLOWED_MATE,
}


def is_critical(loss: MoveLoss, wp_threshold: float) -> bool:
    return loss.win_prob_loss >= wp_threshold or loss.transition in SERIOUS_TRANSITIONS
