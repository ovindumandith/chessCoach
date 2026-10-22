"""Coaching context (what the LLM is shown) and coaching response (what it must return).

The response schema routes every checkable claim into structured fields (game_id, ply,
FEN, best move) so it can be verified against stored evidence. Pydantic checks structure
only; chess truth is checked in validation.py.
"""

import copy

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- context


class EvidencePosition(BaseModel):
    """One analyzed student decision, exactly as stored. Evaluations are student-POV."""

    observation_id: str
    game_id: str
    ply: int
    move_number: int
    student_color: str
    fen: str
    played_move_san: str
    played_move_uci: str
    engine_best_move_san: str | None
    engine_best_move_uci: str | None
    engine_best_line_san: list[str]
    opponent_best_reply_san: list[str]
    eval_before: str  # e.g. "+0.37" or "mate in 1" / "mated in 2"
    eval_after: str
    win_probability_loss: float
    phase: str
    evidence_type: str
    motif_kind: str | None
    review_status: str


class SkillFocus(BaseModel):
    skill_code: str
    subskill_code: str | None
    skill_name: str
    state: str
    error_count: int
    games_affected: int
    opportunity_count: int | None
    error_rate: float | None
    priority_score: float | None
    provisional: bool


class CoachingContext(BaseModel):
    student_id: str
    student_level: str | None
    rating_estimate: int | None
    learning_preferences: dict
    profile_version: int
    objective: SkillFocus
    secondary: SkillFocus | None
    positions: list[EvidencePosition]
    previous_lessons: list[dict]
    exercise_history: list[dict]


# --------------------------------------------------------------------------- response


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LessonExample(_Strict):
    game_id: str = Field(description="Exact game_id of a supplied position.")
    ply: int = Field(description="Exact ply of that supplied position.")
    fen: str = Field(description="The supplied FEN for that position, copied exactly.")
    engine_best_move_uci: str | None = Field(
        description="If you name the engine's best move, copy engine_best_move_uci exactly; "
        "otherwise null."
    )
    explanation: str = Field(description="What happened here and why it matters.")


class CoachingResponse(_Strict):
    objective: str = Field(description="One learning objective, in plain language.")
    skill_code: str = Field(description="The objective skill_code from the context.")
    recurring_pattern: str = Field(description="The observed pattern, grounded in the evidence.")
    examples: list[LessonExample] = Field(description="One or two supplied positions.")
    student_question: str = Field(
        description="A question asking the student to calculate before any solution is shown."
    )
    exercise_recommendation: str
    follow_up_metric: str = Field(description="A measurable criterion for the follow-up.")
    uncertainty: str = Field(description="What the evidence cannot tell us; missing data.")
    verified_facts: list[str] = Field(description="Statements taken directly from the evidence.")
    hypotheses: list[str] = Field(description="Interpretations that are not proven.")


def strict_json_schema(model: type[BaseModel]) -> dict:
    """JSON Schema for structured outputs: $refs inlined, every object closed and with all
    properties required (nullable fields stay required but accept null)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            # Drop the "title"/"default" annotations of a schema node, but never a PROPERTY
            # that happens to be called "title": inside "properties" the keys are field names.
            node = {
                k: (
                    {name: resolve(sub) for name, sub in v.items()}
                    if k == "properties"
                    else resolve(v)
                )
                for k, v in node.items()
                if k not in ("title", "default")
            }
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)
