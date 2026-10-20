"""Pydantic request/response models for the public API."""

import uuid
from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from chesscoach.coaching.schemas import CoachingResponse
from chesscoach.db.enums import (
    AnalysisPass,
    Color,
    EvidenceType,
    ExercisePurpose,
    ExerciseStatus,
    GamePhase,
    GameResult,
    JobStatus,
    MappingStatus,
    ProfileState,
    ReviewStatus,
    ValidationStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- students


class StudentCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(
        default_factory=list,
        description="PGN player names that identify this student (case-insensitive).",
    )
    rating_estimate: int | None = Field(default=None, ge=0, le=4000)
    rating_source: str | None = Field(default=None, max_length=100)
    skill_level: str | None = Field(default=None, max_length=50)
    learning_preferences: dict[str, Any] = Field(default_factory=dict)


class AliasCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=200)


class StudentOut(ORMModel):
    id: uuid.UUID
    display_name: str
    rating_estimate: int | None
    rating_source: str | None
    skill_level: str | None
    learning_preferences: dict[str, Any]
    aliases: list[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, student) -> "StudentOut":
        data = {k: getattr(student, k) for k in cls.model_fields if k != "aliases"}
        return cls(**data, aliases=[a.alias for a in student.aliases])


# --------------------------------------------------------------------------- games


class GameSummary(ORMModel):
    id: uuid.UUID
    student_id: uuid.UUID
    source_file_id: uuid.UUID
    game_index: int
    white_name: str
    black_name: str
    student_color: Color | None
    mapping_status: MappingStatus
    result: GameResult
    played_at: date | None
    time_control: str | None
    opening_eco: str | None
    ply_count: int
    has_clock: bool
    created_at: datetime


class GameDetail(GameSummary):
    pgn_headers: dict[str, Any]
    raw_pgn: str
    import_warnings: list[Any]


class MappingConfirm(BaseModel):
    student_color: Color


class GameImportItemOut(BaseModel):
    index: int
    status: str
    game_id: str | None
    white: str | None
    black: str | None
    student_color: str | None
    mapping_status: str | None
    reason: str | None
    warnings: list[str]


class ImportReportOut(BaseModel):
    source_file_id: str
    sha256: str
    file_previously_uploaded: bool
    encoding: str
    total_records: int
    imported: int
    needs_mapping: int
    duplicates: int
    rejected: int
    file_warnings: list[str]
    games: list[GameImportItemOut]


# --------------------------------------------------------------------------- analysis


class AnalyzeRequest(BaseModel):
    force: bool = Field(default=False, description="Re-run even if a completed analysis exists.")


class AnalysisJobOut(ORMModel):
    id: uuid.UUID
    game_id: uuid.UUID
    pass_type: AnalysisPass
    status: JobStatus
    attempts: int
    analysis_version: str
    engine_name: str | None
    engine_version: str | None
    configuration: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None


class MoveAnalysisOut(ORMModel):
    """Engine evidence for one student move. Evaluations are from the student's view;
    a mate value of 0 after the move means the student delivered checkmate."""

    ply: int
    fen_before: str
    fen_after: str
    uci_move: str
    san_move: str
    phase: GamePhase
    eval_before_cp: int | None
    eval_after_cp: int | None
    eval_before_mate: int | None
    eval_after_mate: int | None
    best_move_uci: str | None
    second_best_cp: int | None
    principal_variation: list[str]
    best_move_loss_cp: int | None
    win_prob_loss: float | None
    search_depth: int | None
    clock_before_ms: int | None
    clock_after_ms: int | None
    features: dict[str, Any]


class GameAnalysisOut(BaseModel):
    game_id: uuid.UUID
    student_color: Color | None
    baseline: AnalysisJobOut
    moves: list[MoveAnalysisOut]
    critical: AnalysisJobOut | None
    critical_moves: list[MoveAnalysisOut]


# --------------------------------------------------------------------------- classification


class ClassifyResultOut(BaseModel):
    game_id: uuid.UUID
    baseline_run_id: uuid.UUID
    critical_run_id: uuid.UUID | None
    moves_classified: int
    observations: int
    opportunities: int
    preserved_reviewed: int
    carried_reviews: int
    classifier_version: str


class MoveEvidenceOut(BaseModel):
    """The analyzed position an observation is based on (student's point of view)."""

    move_analysis_id: uuid.UUID
    ply: int
    fen_before: str
    san_move: str
    uci_move: str
    best_move_uci: str | None
    best_line_san: list[str]
    refutation_san: list[str]
    eval_before_cp: int | None
    eval_before_mate: int | None
    eval_after_cp: int | None
    eval_after_mate: int | None
    win_prob_loss: float | None
    phase: GamePhase


class WeaknessOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    game_id: uuid.UUID
    skill_code: str
    subskill_code: str | None
    evidence_type: EvidenceType
    severity: float | None
    confidence: float | None
    confidence_note: str = "Ordinal heuristic, not a calibrated probability."
    classifier_version: str
    taxonomy_version: str
    review_status: ReviewStatus
    reviewed_at: datetime | None
    review_note: str | None
    details: dict[str, Any]
    created_at: datetime
    game_white: str
    game_black: str
    game_played_at: date | None
    evidence: MoveEvidenceOut

    @classmethod
    def from_view(cls, view) -> "WeaknessOut":
        o, m, g = view.observation, view.move, view.game
        return cls(
            id=o.id,
            student_id=o.student_id,
            game_id=o.game_id,
            skill_code=o.skill_code,
            subskill_code=o.subskill_code,
            evidence_type=o.evidence_type,
            severity=o.severity,
            confidence=o.confidence,
            classifier_version=o.classifier_version,
            taxonomy_version=o.taxonomy_version,
            review_status=o.review_status,
            reviewed_at=o.reviewed_at,
            review_note=o.review_note,
            details=o.details,
            created_at=o.created_at,
            game_white=g.white_name,
            game_black=g.black_name,
            game_played_at=g.played_at,
            evidence=MoveEvidenceOut(
                move_analysis_id=m.id,
                ply=m.ply,
                fen_before=m.fen_before,
                san_move=m.san_move,
                uci_move=m.uci_move,
                best_move_uci=m.best_move_uci,
                best_line_san=m.features.get("pv_san", []),
                refutation_san=m.features.get("refutation_san", []),
                eval_before_cp=m.eval_before_cp,
                eval_before_mate=m.eval_before_mate,
                eval_after_cp=m.eval_after_cp,
                eval_after_mate=m.eval_after_mate,
                win_prob_loss=m.win_prob_loss,
                phase=m.phase,
            ),
        )


class ReviewRequest(BaseModel):
    action: Literal["confirm", "reject", "correct"]
    skill_code: str | None = Field(default=None, description="Required for 'correct'.")
    subskill_code: str | None = None
    note: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- profiles


class SkillProfileOut(ORMModel):
    skill_code: str
    subskill_code: str | None
    state: ProfileState
    error_rate: float | None = Field(
        description="Beta-Binomial smoothed rate of the driving channel."
    )
    opportunity_count: int | None
    error_count: int
    games_affected: int
    confidence: float | None = Field(description="Data share of the posterior mean, n/(n+a+b).")
    priority_score: float | None = Field(
        description="Training-priority heuristic E*S*R*C. Not a validated measure of ability."
    )
    evidence_summary: dict[str, Any]


class ProfileSnapshotOut(ORMModel):
    id: uuid.UUID
    student_id: uuid.UUID
    profile_version: int
    cutoff_date: date | None
    triggered_by: str
    generated_at: datetime
    settings: dict[str, Any]
    summary: dict[str, Any]


class ProfileOut(BaseModel):
    snapshot: ProfileSnapshotOut
    stale: bool = Field(description="True if evidence changed since this snapshot was built.")
    skills: list[SkillProfileOut]


class RebuildRequest(BaseModel):
    cutoff_date: date | None = Field(
        default=None, description="Research use: only games played before this date."
    )


# --------------------------------------------------------------------------- coaching


class LessonRequest(BaseModel):
    skill_code: str | None = Field(
        default=None, description="Coach a specific skill instead of the top priority."
    )
    subskill_code: str | None = None


class CoachingSessionOut(ORMModel):
    id: uuid.UUID
    student_id: uuid.UUID
    model_provider: str
    model_id: str
    prompt_version: str
    validation_status: ValidationStatus
    validation_errors: list[Any]
    evidence_references: list[Any]
    token_usage: dict[str, Any]
    latency_ms: int | None
    response_json: dict[str, Any]
    created_at: datetime


class LessonOut(BaseModel):
    session: CoachingSessionOut
    used_fallback: bool = Field(
        description="True when the deterministic template was used instead of the LLM."
    )
    lesson: CoachingResponse


# --------------------------------------------------------------------------- exercises


class ExerciseCreate(BaseModel):
    skill_code: str | None = Field(default=None, description="Defaults to the top priority.")
    subskill_code: str | None = None
    count: int = Field(default=5, ge=1, le=10)


class ExerciseAttemptOut(BaseModel):
    attempt_number: int
    move_uci: str
    move_san: str
    is_correct: bool
    hints_used: int
    time_taken_ms: int | None


class ExerciseOut(BaseModel):
    """Student-safe view: `solution` is null until the exercise is finished."""

    id: uuid.UUID
    student_id: uuid.UUID
    skill_code: str
    subskill_code: str | None
    purpose: ExercisePurpose
    status: ExerciseStatus
    start_fen: str
    side_to_move: Color
    prompt: str
    difficulty: str | None
    max_attempts: int
    attempts: list[ExerciseAttemptOut]
    hints_given: int
    hints_available: int
    created_at: datetime
    finished_at: datetime | None
    solution: dict[str, Any] | None


class AttemptRequest(BaseModel):
    move: str = Field(min_length=2, max_length=10, description="UCI (e2e4) or SAN (Nf3).")
    time_taken_ms: int | None = Field(default=None, ge=0)


class AttemptOut(BaseModel):
    correct: bool
    attempts_left: int
    exercise: ExerciseOut


class HintOut(BaseModel):
    hint: str
    hints_given: int
    hints_remaining: int
