import pytest

from chesscoach.coaching.fallback import build_fallback
from chesscoach.coaching.schemas import (
    CoachingContext,
    CoachingResponse,
    EvidencePosition,
    SkillFocus,
    strict_json_schema,
)
from chesscoach.coaching.validation import validate_response

# 4.Qe2 instead of 4.Qxf7# (student is White).
FEN = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"


def position(game="g1", ply=7, **kw):
    data = dict(
        observation_id="o1",
        game_id=game,
        ply=ply,
        move_number=4,
        student_color="white",
        fen=FEN,
        played_move_san="Qe2",
        played_move_uci="h5e2",
        engine_best_move_san="Qxf7#",
        engine_best_move_uci="h5f7",
        engine_best_line_san=["Qxf7#"],
        opponent_best_reply_san=["Nd4"],
        eval_before="mate in 1",
        eval_after="-2.31",
        win_probability_loss=0.7,
        phase="opening",
        evidence_type="motif",
        motif_kind="missed",
        review_status="candidate",
    )
    data.update(kw)
    return EvidencePosition(**data)


def context(positions=None):
    focus = SkillFocus(
        skill_code="tactical_awareness",
        subskill_code="mating_patterns",
        skill_name="Tactical awareness: Mating patterns",
        state="emerging_pattern",
        error_count=2,
        games_affected=2,
        opportunity_count=2,
        error_rate=0.5,
        priority_score=0.2,
        provisional=True,
    )
    return CoachingContext(
        student_id="s1",
        student_level=None,
        rating_estimate=None,
        learning_preferences={},
        profile_version=1,
        objective=focus,
        secondary=None,
        positions=positions or [position()],
        previous_lessons=[],
        exercise_history=[],
    )


def response(**overrides):
    data = dict(
        objective="Spot forcing mates around f7.",
        skill_code="tactical_awareness",
        recurring_pattern="You played Qe2 when mate in 1 was available.",
        examples=[
            dict(
                game_id="g1",
                ply=7,
                fen=FEN,
                engine_best_move_uci="h5f7",
                explanation="After Qe2 the evaluation went from mate in 1 to -2.31, "
                "and Nd4 hits the queen.",
            )
        ],
        student_question="In this position, what are all of White's checks?",
        exercise_recommendation="Ten mate-in-one puzzles on f7.",
        follow_up_metric="9 of 10 correct on unseen positions.",
        uncertainty="Only two games so far.",
        verified_facts=["Qxf7# was available."],
        hypotheses=["Checking every check first may help."],
    )
    data.update(overrides)
    return CoachingResponse.model_validate(data)


def test_grounded_response_passes():
    assert validate_response(response(), context()) == []


def test_skill_must_match_objective():
    assert any(
        "objective" in e for e in validate_response(response(skill_code="calculation"), context())
    )


@pytest.mark.parametrize(
    "example_override, fragment",
    [
        ({"game_id": "other"}, "unknown position"),
        ({"ply": 9}, "unknown position"),
        ({"fen": FEN.replace("4 4", "0 1")}, "FEN does not match"),
        ({"engine_best_move_uci": "h5h8"}, "not legal"),  # the h7 pawn blocks the h-file
        ({"engine_best_move_uci": "c4f7"}, "differs from the stored engine move"),
    ],
)
def test_example_checks(example_override, fragment):
    ex = {**response().examples[0].model_dump(), **example_override}
    errors = validate_response(response(examples=[ex]), context())
    assert any(fragment in e for e in errors), errors


def test_example_count_bounds():
    ex = response().examples[0].model_dump()
    assert validate_response(response(examples=[]), context())
    assert any(
        "1-2 examples" in e for e in validate_response(response(examples=[ex, ex, ex]), context())
    )


def test_invented_move_is_rejected():
    errors = validate_response(
        response(recurring_pattern="You often miss Bxf7+ and Ng5."), context()
    )
    assert any("'Bxf7+'" in e for e in errors)
    assert any("'Ng5'" in e for e in errors)


def test_square_names_and_pawn_pushes_are_not_moves():
    ok = response(recurring_pattern="The f7 square was weak after e4 and e5.")
    assert validate_response(ok, context()) == []


def test_invented_evaluations_are_rejected():
    errors = validate_response(response(uncertainty="It was +3.50, roughly mate in 3."), context())
    assert any("+3.50" in e for e in errors)
    assert any("mate in 3" in e for e in errors)


def test_question_must_not_reveal_the_solution():
    errors = validate_response(response(student_question="Can you find Qxf7# here?"), context())
    assert "student_question reveals the solution" in errors


def test_fallback_lesson_always_validates():
    ctx = context([position(), position(game="g2", ply=9, observation_id="o2")])
    lesson = build_fallback(ctx)
    assert validate_response(lesson, ctx) == []
    assert {e.game_id for e in lesson.examples} == {"g1", "g2"}
    assert "not been reviewed" in lesson.uncertainty


def test_strict_schema_is_closed_and_ref_free():
    schema = strict_json_schema(CoachingResponse)
    text = str(schema)
    assert "$ref" not in text
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    item = schema["properties"]["examples"]["items"]
    assert item["additionalProperties"] is False and "engine_best_move_uci" in item["required"]
