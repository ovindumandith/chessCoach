"""The student's puzzle rating per skill: a Glicko-style update against each puzzle.

The puzzle's own RatingDeviation damps the update through g(RD): a puzzle whose rating is
uncertain moves the student's rating less. Pure functions; parameters are versioned with
the selection settings.
"""

import math

Q = math.log(10) / 400


def g(rd: float) -> float:
    """Glicko's attenuation factor for an opponent (here: puzzle) with deviation `rd`."""
    return 1 / math.sqrt(1 + 3 * Q**2 * rd**2 / math.pi**2)


def expected(student: float, puzzle: float, puzzle_rd: float) -> float:
    """Probability that the student solves the puzzle."""
    return 1 / (1 + 10 ** (-g(puzzle_rd) * (student - puzzle) / 400))


def updated(student: float, puzzle: float, puzzle_rd: float, solved: bool, *, k: float) -> float:
    s = 1.0 if solved else 0.0
    return student + k * g(puzzle_rd) * (s - expected(student, puzzle, puzzle_rd))
