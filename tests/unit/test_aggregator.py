import pytest

from chesscoach.classification.taxonomy import get_taxonomy
from chesscoach.db.enums import ProfileState
from chesscoach.profiling.aggregator import (
    SETTINGS,
    MoveFact,
    ObsFact,
    OppFact,
    build_profile,
    exposure_rule,
)

TAX = get_taxonomy()
HANGING = ("tactical_awareness", "hanging_pieces")
FORKS = ("tactical_awareness", "forks")


def moves(games=5, per_game=10, **kw):
    out = []
    for g in range(games):
        for i in range(per_game):
            out.append(
                MoveFact(
                    game_id=f"g{g}",
                    move_analysis_id=f"g{g}m{i}",
                    game_order=g,
                    phase=kw.get("phase", "middlegame"),
                    wp_before=kw.get("wp_before", 0.5),
                    only_move_gap=None,
                    forced=kw.get("forced", False),
                    time_trouble=False,
                    endgame_type=kw.get("endgame_type"),
                )
            )
    return out


def obs(
    game,
    move,
    key=HANGING,
    status="candidate",
    kind="allowed",
    severity=0.2,
    oid=None,
    original=None,
):
    return ObsFact(
        id=oid or f"o-{game}-{move}-{key[1]}",
        game_id=f"g{game}",
        move_analysis_id=f"g{game}m{move}",
        game_order=game,
        phase="middlegame",
        skill_code=key[0],
        subskill_code=key[1],
        evidence_type="motif",
        motif_kind=kind,
        severity=severity,
        review_status=status,
        original_key=original,
    )


def skill(result, key):
    return next(s for s in result.skills if s.key == key)


def build(m, o=(), p=(), previous=None):
    games = len({x.game_id for x in m})
    return build_profile(TAX, m, list(o), list(p), games_included=games, previous=previous)


def test_every_auto_skill_present_and_clean_history_is_no_issue():
    result = build(moves())
    keys = {s.key for s in result.skills}
    assert ("unclassified", None) in keys and HANGING in keys
    unclassified = skill(result, ("unclassified", None))
    assert unclassified.state == ProfileState.NO_ISSUE_DETECTED
    assert unclassified.priority is None  # not a trainable skill
    assert result.summary["moves_analyzed"] == 50


def test_too_little_history_is_insufficient():
    assert (
        skill(build(moves(games=2)), ("unclassified", None)).state
        == ProfileState.INSUFFICIENT_EVIDENCE
    )


def test_many_errors_in_one_game_are_never_a_weakness():
    errors = [obs(0, i, status="confirmed") for i in range(4)]
    s = skill(build(moves(), errors), HANGING)
    assert s.error_count == 4
    assert s.games_affected == 1
    assert s.state == ProfileState.INSUFFICIENT_EVIDENCE


def test_two_games_emerging_and_recurring_needs_three_plus_rate():
    two = [obs(0, 1), obs(1, 1)]
    assert skill(build(moves(), two), HANGING).state == ProfileState.EMERGING_PATTERN
    many = [obs(g, i, status="confirmed") for g in range(4) for i in range(2)]
    assert skill(build(moves(), many), HANGING).state == ProfileState.RECURRING_WEAKNESS


def test_exposure_rate_is_beta_binomial_with_review_weights():
    errors = [
        obs(0, 1, status="confirmed"),
        obs(1, 1, status="candidate"),
        obs(2, 1, status="rejected"),
    ]
    s = skill(build(moves(), errors), HANGING)
    channel = s.summary["channels"]["exposure"]
    a, b = SETTINGS["priors"]["exposure"]["alpha"], SETTINGS["priors"]["exposure"]["beta"]
    assert channel["n"] == 50
    assert channel["e_effective"] == pytest.approx(1.5)  # 1 confirmed + 0.5 candidate
    assert s.error_rate == pytest.approx((1.5 + a) / (50 + a + b), abs=1e-6)
    assert s.error_count == 2  # the rejected one is gone
    assert s.summary["reviewed_errors"] == 1


def test_detected_channel_uses_opportunities():
    m = moves()
    opps = [OppFact(f"g{g}", f"g{g}m0", *FORKS, "missed") for g in range(4)]
    opps += [OppFact(f"g{g}", f"g{g}m1", *FORKS, "converted") for g in range(2)]
    missed = [obs(g, 0, key=FORKS, kind="missed", status="confirmed") for g in range(4)]
    s = skill(build(m, missed, opps), FORKS)
    detected = s.summary["channels"]["detected"]
    assert (detected["n"], detected["e_effective"]) == (6, 4.0)
    assert detected["p_hat"] == pytest.approx((4 + 1) / (6 + 1 + 2))
    assert s.summary["driving_channel"] == "detected"
    assert s.opportunity_count == 6
    assert s.state == ProfileState.RECURRING_WEAKNESS


def test_rejected_missed_motif_drops_its_opportunity():
    opps = [OppFact("g0", "g0m0", *FORKS, "missed"), OppFact("g1", "g1m0", *FORKS, "converted")]
    rejected = [obs(0, 0, key=FORKS, kind="missed", status="rejected")]
    detected = skill(build(moves(), rejected, opps), FORKS).summary["channels"]["detected"]
    assert (detected["n"], detected["e_effective"]) == (1, 0)


def test_correction_moves_evidence_to_the_new_skill():
    opps = [OppFact("g0", "g0m0", *FORKS, "missed")]
    corrected = [
        obs(
            0,
            0,
            key=("calculation", "forcing_variations"),
            kind="missed",
            status="corrected",
            original=FORKS,
        )
    ]
    result = build(moves(), corrected, opps)
    assert skill(result, FORKS).summary["channels"]["detected"]["n"] == 0
    coach = skill(result, ("calculation", "forcing_variations"))
    assert coach.error_count == 1
    assert coach.opportunity_count is None  # no exposure model for coach-only skills
    assert coach.summary["coach_labelled_only"] is True
    assert coach.priority > 0


def test_priority_orders_recurring_above_isolated():
    errors = [obs(g, 1, status="confirmed", severity=0.3) for g in range(4)]
    errors += [obs(0, 2, key=("defensive_skills", "threat_prevention"), severity=0.3)]
    result = build(moves(), errors)
    assert result.skills[0].key == HANGING
    components = result.skills[0].summary["components"]
    assert result.skills[0].priority == pytest.approx(
        components["E"] * components["S"] * components["R"] * components["C"], abs=1e-5
    )


def test_forced_moves_do_not_count_as_exposure():
    s = skill(build(moves(forced=True)), ("unclassified", None))
    assert s.summary["channels"]["exposure"]["n"] == 0
    assert s.state == ProfileState.INSUFFICIENT_EVIDENCE


def test_examples_are_one_per_game_highest_severity_first():
    errors = [obs(0, 1, severity=0.1), obs(0, 2, severity=0.5), obs(1, 1, severity=0.3)]
    examples = skill(build(moves(), errors), HANGING).summary["example_observation_ids"]
    assert examples == ["o-0-2-hanging_pieces", "o-1-1-hanging_pieces"]


def test_change_against_previous_snapshot():
    previous = {
        HANGING: {
            "profile_version": 1,
            "state": "emerging_pattern",
            "error_rate": 0.5,
            "priority_score": 0.1,
        }
    }
    errors = [obs(g, 1, status="confirmed") for g in range(4)]
    change = skill(build(moves(), errors, previous=previous), HANGING).summary["change"]
    assert change["previous_version"] == 1
    assert change["state_changed"] is True
    assert change["error_rate_delta"] < 0


def test_needs_diagnostic_when_a_channel_is_unobserved():
    s = skill(build(moves()), FORKS)  # plenty of moves, zero fork opportunities
    assert s.summary["needs_diagnostic"] is True


def test_exposure_rules():
    m = moves(games=1, per_game=1, phase="endgame", endgame_type="rook_endgames", wp_before=0.9)[0]
    assert exposure_rule(("endgame_technique", "rook_endgames"))(m)
    assert not exposure_rule(("endgame_technique", "pawn_endgames"))(m)
    assert exposure_rule(("winning_position_conversion", "preserving_advantage"))(m)
    assert exposure_rule(("opening_knowledge", "opening_traps")) is None


def test_unexplained_errors_never_outrank_skills():
    errors = [obs(g, 1, key=("unclassified", None), severity=0.5) for g in range(5)]
    errors += [obs(g, 2, severity=0.1) for g in range(2)]
    result = build(moves(), errors)
    unclassified = skill(result, ("unclassified", None))
    assert unclassified.state == ProfileState.RECURRING_WEAKNESS
    assert unclassified.priority is None
    assert unclassified.summary["actionable"] is False
    assert result.skills[0].key == HANGING
    assert result.skills[-1].key != HANGING
