"""profile-v1: aggregate classified evidence into per-skill profile entries. Pure functions.

Every skill is measured through up to two channels, never mixed in one ratio:

- detected: positions where the skill was demonstrably tested (Phase 4 skill
  opportunities, such as a fork that was available and needed). Error = a missed one.
- exposure: moves played in the relevant context (all moves for "hung a piece", endgame
  moves for endgame skills, time-trouble moves for time management). Error = a classified
  observation on such a move.

Rates are Beta-Binomial smoothed: p = (e + a) / (n + a + b). Errors are weighted by
review status: confirmed or corrected = 1, unreviewed candidate = `candidate_weight`,
rejected = excluded. Recurrence is measured in distinct GAMES, never moves.

The priority P = E*S*R*C is a training-priority heuristic, NOT a validated measure of
chess ability. All parameters are versioned in SETTINGS and still need empirical evaluation.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from chesscoach.classification.classifier import THRESHOLDS
from chesscoach.classification.taxonomy import UNCLASSIFIED, Taxonomy
from chesscoach.db.enums import ProfileState

PROFILE_VERSION = "profile-v1"

SETTINGS = {
    "profile_version": PROFILE_VERSION,
    "candidate_weight": 0.5,
    "priors": {"detected": {"alpha": 1.0, "beta": 2.0}, "exposure": {"alpha": 0.5, "beta": 24.5}},
    "reference_rate": {"detected": 0.6, "exposure": 0.06},
    "severity_reference": 0.30,
    "recurrence_cap_games": 4,
    "coach_only_scale": 0.5,
    "min_games_for_state": 3,
    "min_opportunities": 5,
    "recurring_min_games": 3,
    "recurring_min_e": 0.3,
    "emerging_min_games": 2,
    "recent_games": 10,
    "max_examples": 5,
    "min_exercises_for_reliability": 5,
}

REVIEWED = {"confirmed", "corrected"}
TACTICAL = "tactical_awareness"

Key = tuple[str, str | None]


@dataclass(frozen=True)
class MoveFact:
    game_id: str
    move_analysis_id: str
    game_order: int  # 0 = oldest game
    phase: str
    wp_before: float
    only_move_gap: float | None
    forced: bool
    time_trouble: bool
    endgame_type: str | None


@dataclass(frozen=True)
class ObsFact:
    id: str
    game_id: str
    move_analysis_id: str
    game_order: int
    phase: str
    skill_code: str
    subskill_code: str | None
    evidence_type: str
    motif_kind: str | None
    severity: float
    review_status: str
    original_key: Key | None = None


@dataclass(frozen=True)
class OppFact:
    game_id: str
    move_analysis_id: str
    skill_code: str
    subskill_code: str | None
    outcome: str  # converted | missed


@dataclass(frozen=True)
class ExerciseFact:
    skill_code: str
    subskill_code: str | None
    first_try_correct: bool


@dataclass
class Channel:
    name: str
    n: int
    e_effective: float
    e_confirmed: int
    e_candidate: int
    p_hat: float
    e_score: float  # E: p_hat relative to the channel's reference rate, clipped to [0, 1]
    c_score: float  # C: share of the posterior mean coming from data, n / (n + a + b)

    def as_dict(self) -> dict:
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


@dataclass
class SkillResult:
    skill_code: str
    subskill_code: str | None
    state: ProfileState
    error_rate: float | None
    opportunity_count: int | None
    error_count: int
    games_affected: int
    confidence: float | None
    priority: float | None
    summary: dict = field(default_factory=dict)

    @property
    def key(self) -> Key:
        return (self.skill_code, self.subskill_code)


@dataclass
class ProfileResult:
    skills: list[SkillResult]
    summary: dict


# --------------------------------------------------------------------------- exposure rules


def exposure_rule(key: Key) -> Callable[[MoveFact], bool] | None:
    """Which moves expose the student to a skill. None = no exposure model (coach-only)."""
    skill, sub = key
    if skill == UNCLASSIFIED:
        return lambda m: True
    if skill == TACTICAL and sub in ("forks", "hanging_pieces", "mating_patterns"):
        return lambda m: True  # every move can allow a tactic
    if skill == "endgame_technique" and sub in (
        "pawn_endgames",
        "rook_endgames",
        "general_endgames",
    ):
        return lambda m: m.phase == "endgame" and m.endgame_type == sub
    if key == ("winning_position_conversion", "preserving_advantage"):
        return lambda m: m.wp_before >= THRESHOLDS["winning_wp"]
    if key == ("defensive_skills", "finding_resources"):
        return lambda m: (
            THRESHOLDS["defensive_min_wp"] <= m.wp_before < THRESHOLDS["winning_wp"]
            and m.only_move_gap is not None
            and m.only_move_gap >= THRESHOLDS["only_move_gap"]
        )
    if key == ("defensive_skills", "threat_prevention"):
        return lambda m: True
    if key == ("practical_play", "time_management"):
        return lambda m: m.time_trouble
    return None


def has_detected_channel(key: Key) -> bool:
    return key[0] == TACTICAL and key[1] in ("forks", "hanging_pieces", "mating_patterns")


def auto_keys(taxonomy: Taxonomy) -> list[Key]:
    keys: list[Key] = [(UNCLASSIFIED, None)]
    for code, cat in taxonomy.categories.items():
        keys += [(code, sub) for sub, spec in cat.subskills.items() if spec.auto]
    return keys


# --------------------------------------------------------------------------- aggregation


def build_profile(
    taxonomy: Taxonomy,
    moves: list[MoveFact],
    observations: list[ObsFact],
    opportunities: list[OppFact],
    *,
    games_included: int,
    previous: dict[Key, dict] | None = None,
    exercises: list[ExerciseFact] = (),
    settings: dict = SETTINGS,
) -> ProfileResult:
    keys = auto_keys(taxonomy)
    keys += sorted(
        {(o.skill_code, o.subskill_code) for o in observations if o.review_status != "rejected"}
        - set(keys),
        key=str,
    )
    max_order = max((m.game_order for m in moves), default=-1)
    skills = [
        _skill(
            key, moves, observations, opportunities, settings, max_order, (previous or {}).get(key)
        )
        for key in keys
    ]
    for s in skills:
        s.summary["exercises"] = _exercise_summary(s.key, exercises, settings)
    skills.sort(key=lambda s: (-(s.priority or 0.0), s.skill_code, s.subskill_code or ""))
    return ProfileResult(skills=skills, summary=_summary(moves, observations, games_included))


def _weight(status: str, settings: dict) -> float:
    if status == "rejected":
        return 0.0
    return 1.0 if status in REVIEWED else settings["candidate_weight"]


def _channel(name: str, n: int, weighted: list[tuple[float, str]], settings: dict) -> Channel:
    prior = settings["priors"][name]
    a, b = prior["alpha"], prior["beta"]
    e = min(float(n), sum(w for w, _ in weighted))
    p_hat = (e + a) / (n + a + b)
    return Channel(
        name=name,
        n=n,
        e_effective=e,
        e_confirmed=sum(1 for _, s in weighted if s in REVIEWED),
        e_candidate=sum(1 for _, s in weighted if s not in REVIEWED),
        p_hat=p_hat,
        e_score=min(1.0, p_hat / settings["reference_rate"][name]),
        c_score=n / (n + a + b),
    )


def _matches(o: ObsFact, key: Key) -> bool:
    return (o.skill_code, o.subskill_code) == key


def _skill(key, moves, observations, opportunities, settings, max_order, previous) -> SkillResult:
    channels: dict[str, Channel] = {}
    counted: dict[str, ObsFact] = {}  # move_analysis_id -> strongest observation for this key

    # Detected channel: available-and-needed opportunities.
    if has_detected_channel(key):
        weighted = []
        n = 0
        for opp in opportunities:
            if (opp.skill_code, opp.subskill_code) != key:
                continue
            linked = [
                o
                for o in observations
                if o.move_analysis_id == opp.move_analysis_id
                and o.motif_kind == "missed"
                and (_matches(o, key) or o.original_key == key)
            ]
            # The coach said this was not a missed instance of this skill: drop it entirely.
            if any(o.review_status == "rejected" or not _matches(o, key) for o in linked):
                continue
            n += 1
            if opp.outcome == "missed":
                status = linked[0].review_status if linked else "candidate"
                weighted.append((_weight(status, settings), status))
                if linked:
                    counted[opp.move_analysis_id] = linked[0]
        channels["detected"] = _channel("detected", n, weighted, settings)

    # Exposure channel: moves in the relevant context.
    rule = exposure_rule(key)
    exposure_obs = [
        o
        for o in observations
        if _matches(o, key)
        and o.review_status != "rejected"
        and not (has_detected_channel(key) and o.motif_kind == "missed")
    ]
    by_move: dict[str, ObsFact] = {}
    for o in exposure_obs:
        best = by_move.get(o.move_analysis_id)
        if best is None or _weight(o.review_status, settings) > _weight(
            best.review_status, settings
        ):
            by_move[o.move_analysis_id] = o
    exposure_games: set[str] = set()
    if rule is not None:
        exposed = [m for m in moves if not m.forced and rule(m)]
        exposure_games = {m.game_id for m in exposed}
        weighted = [(_weight(o.review_status, settings), o.review_status) for o in by_move.values()]
        channels["exposure"] = _channel("exposure", len(exposed), weighted, settings)
    counted.update(by_move)
    exposure_games |= {o.game_id for o in opportunities if (o.skill_code, o.subskill_code) == key}

    errors = list(counted.values())
    games_affected = len({o.game_id for o in errors})
    mean_sev = sum(o.severity for o in errors) / len(errors) if errors else 0.0
    s_score = min(1.0, mean_sev / settings["severity_reference"])
    r_score = (
        min(games_affected, settings["recurrence_cap_games"]) / settings["recurrence_cap_games"]
    )

    # Only channels with data may drive: with n = 0 the smoothed rate is just the prior mean,
    # which would otherwise outrank a real but lower observed rate.
    observed = [c for c in channels.values() if c.n > 0]
    driving = max(observed, key=lambda c: (c.e_score, c.n), default=None)
    if driving is not None:
        priority = driving.e_score * s_score * r_score * driving.c_score
        error_rate, n_driving, confidence = driving.p_hat, driving.n, driving.c_score
        e_for_state = driving.e_score
    else:
        # No exposure model (coach-labelled skills) or no exposure at all.
        priority = s_score * r_score * settings["coach_only_scale"] if errors else 0.0
        error_rate = n_driving = confidence = None
        e_for_state = None

    if key[0] == UNCLASSIFIED:
        # Unexplained errors are not a trainable skill. They are a coach review queue, so
        # they never compete for training priority.
        priority = None

    max_n = max((c.n for c in channels.values()), default=0)
    state = _state(
        errors,
        games_affected,
        len(exposure_games),
        max_n,
        e_for_state,
        rule is None and not has_detected_channel(key),
        settings,
    )

    reviewed = sum(1 for o in errors if o.review_status in REVIEWED)
    recent_from = max_order - settings["recent_games"] + 1
    summary = {
        "channels": {name: c.as_dict() for name, c in channels.items()},
        "driving_channel": driving.name if driving is not None else None,
        "components": {
            "E": round(e_for_state, 6) if e_for_state is not None else None,
            "S": round(s_score, 6),
            "R": round(r_score, 6),
            "C": round(confidence, 6) if confidence is not None else None,
        },
        "mean_severity": round(mean_sev, 6),
        "exposure_games": len(exposure_games),
        "reviewed_errors": reviewed,
        "provisional": bool(errors) and reviewed / len(errors) < 0.5,
        # Exploration: some channel has barely been observed, so a diagnostic exercise is
        # worth more than silence (e.g. no fork opportunities seen yet).
        "needs_diagnostic": min((c.n for c in channels.values()), default=0)
        < settings["min_opportunities"],
        "coach_labelled_only": rule is None and not has_detected_channel(key),
        "actionable": key[0] != UNCLASSIFIED,
        "recent_errors": sum(1 for o in errors if o.game_order >= recent_from),
        "last_error_game_order": max((o.game_order for o in errors), default=None),
        "example_observation_ids": _examples(errors, settings["max_examples"]),
    }
    if previous:
        summary["change"] = _change(previous, state, error_rate, priority)

    return SkillResult(
        skill_code=key[0],
        subskill_code=key[1],
        state=state,
        error_rate=round(error_rate, 6) if error_rate is not None else None,
        opportunity_count=n_driving,
        error_count=len(errors),
        games_affected=games_affected,
        confidence=round(confidence, 6) if confidence is not None else None,
        priority=round(priority, 6) if priority is not None else None,
        summary=summary,
    )


def _exercise_summary(key: Key, exercises: list[ExerciseFact], settings: dict) -> dict:
    """First-try exercise accuracy. Informational only: it never changes E, S, R, C,
    priority or state (a single exercise must not change a profile)."""
    mine = [e for e in exercises if (e.skill_code, e.subskill_code) == key]
    correct = sum(1 for e in mine if e.first_try_correct)
    return {
        "attempted": len(mine),
        "solved_first_try": correct,
        "first_try_accuracy": round(correct / len(mine), 4) if mine else None,
        "reliable": len(mine) >= settings["min_exercises_for_reliability"],
        "affects_priority": False,
    }


def _state(
    errors, games_affected, exposure_games, max_n, e_score, coach_only, settings
) -> ProfileState:
    if not errors:
        enough = exposure_games >= settings["min_games_for_state"] and (
            max_n >= settings["min_opportunities"]
        )
        return ProfileState.NO_ISSUE_DETECTED if enough else ProfileState.INSUFFICIENT_EVIDENCE
    if games_affected >= settings["recurring_min_games"] and (
        coach_only or (e_score is not None and e_score >= settings["recurring_min_e"])
    ):
        return ProfileState.RECURRING_WEAKNESS
    if games_affected >= settings["emerging_min_games"]:
        return ProfileState.EMERGING_PATTERN
    # One affected game is never a persistent weakness (project.md §15).
    return ProfileState.INSUFFICIENT_EVIDENCE


def _examples(errors: list[ObsFact], limit: int) -> list[str]:
    """Highest-severity evidence, at most one per game, for coaching retrieval."""
    chosen, games = [], set()
    for o in sorted(errors, key=lambda o: -o.severity):
        if o.game_id not in games:
            chosen.append(o.id)
            games.add(o.game_id)
        if len(chosen) == limit:
            break
    return chosen


def _change(previous: dict, state, error_rate, priority) -> dict:
    def delta(new, old):
        return round(new - old, 6) if new is not None and old is not None else None

    return {
        "previous_version": previous.get("profile_version"),
        "previous_state": previous.get("state"),
        "state_changed": previous.get("state") != state.value,
        "error_rate_delta": delta(error_rate, previous.get("error_rate")),
        "priority_delta": delta(priority, previous.get("priority_score")),
    }


def _summary(moves: list[MoveFact], observations: Iterable[ObsFact], games_included: int) -> dict:
    by_phase: dict[str, dict] = defaultdict(lambda: {"moves": 0, "error_moves": 0})
    for m in moves:
        if not m.forced:
            by_phase[m.phase]["moves"] += 1
    error_moves: dict[str, str] = {}
    for o in observations:
        if o.review_status != "rejected":
            error_moves[o.move_analysis_id] = o.phase
    for phase in error_moves.values():
        by_phase[phase]["error_moves"] += 1
    for stats in by_phase.values():
        stats["error_share"] = (
            round(stats["error_moves"] / stats["moves"], 6) if stats["moves"] else None
        )
    return {
        "games_included": games_included,
        "moves_analyzed": sum(1 for m in moves if not m.forced),
        "by_phase": dict(by_phase),
    }


def previous_index(rows: Iterable, profile_version: int) -> dict[Key, dict]:
    """Index a previous snapshot's skill rows for change tracking."""
    return {
        (r.skill_code, r.subskill_code): {
            "profile_version": profile_version,
            "state": r.state.value,
            "error_rate": r.error_rate,
            "priority_score": r.priority_score,
        }
        for r in rows
    }
