"""Choosing a set of puzzles that gets harder: pure functions over candidate rows.

A set has one puzzle per target rating, targets stepping up from the student's current
puzzle rating for the skill. For each target the chosen puzzle is the one whose rating
interval (Rating ± RatingDeviation) covers the target and is closest to it, preferring
popular puzzles; every puzzle in a set is rated strictly higher than the one before.
"""

from dataclasses import dataclass

SELECTION = {
    "version": "puzzle-select-v1",
    "offsets": [-200, -75, 75, 200],  # four puzzles, easiest first
    "window": 100,  # first search radius around a target; doubled up to `max_widen` times
    "max_widen": 3,
    "max_rd": 110,  # never select a puzzle whose rating is less certain than this
    "min_rating": 400,
    "max_rating": 3000,
    "default_rating": 1500,  # Lichess's starting puzzle rating, if the student has none
    "k": 32,
    "k_provisional": 64,  # faster moves while the rating for a skill is still new
    "provisional_puzzles": 8,
}


@dataclass(frozen=True)
class Candidate:
    puzzle_id: object
    theme: str
    rating: int
    rating_deviation: int
    popularity: int


def targets(base: float, settings: dict = SELECTION) -> list[int]:
    lo, hi = settings["min_rating"], settings["max_rating"]
    return [int(min(hi, max(lo, round(base + o)))) for o in settings["offsets"]]


def score(c: Candidate, target: int) -> tuple:
    distance = abs(c.rating - target)
    return (distance > c.rating_deviation, distance, -c.popularity, c.rating)


def pick(candidates: list[Candidate], target: int, above: int | None) -> Candidate | None:
    """The best candidate for `target` that is rated strictly higher than `above`."""
    eligible = [c for c in candidates if above is None or c.rating > above]
    return min(eligible, key=lambda c: score(c, target), default=None)
