"""SQLAlchemy ORM models. See docs/DATA_MODEL.md for the rationale behind each table."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from chesscoach.db.enums import (
    AccessLevel,
    AnalysisPass,
    Color,
    EvidenceType,
    ExercisePurpose,
    ExerciseStatus,
    GamePhase,
    GameResult,
    ImportStatus,
    JobStatus,
    MappingStatus,
    OpportunityOutcome,
    PlanStatus,
    ProfileState,
    PuzzleResult,
    PuzzleStatus,
    ReviewStatus,
    UserRole,
    ValidationStatus,
)
from chesscoach.db.types import JSONType, UTCDateTime, new_uuid, str_enum, utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        datetime: UTCDateTime(),
        dict[str, Any]: JSONType,
        list[Any]: JSONType,
    }


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=new_uuid)


# --------------------------------------------------------------------------- users & students


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    external_auth_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, "user_role"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Student(TimestampMixin, Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = _pk()
    display_name: Mapped[str] = mapped_column(String(200))
    rating_estimate: Mapped[int | None] = mapped_column(Integer)
    rating_source: Mapped[str | None] = mapped_column(String(100))
    skill_level: Mapped[str | None] = mapped_column(String(50))
    learning_preferences: Mapped[dict[str, Any]] = mapped_column(default=dict)

    aliases: Mapped[list["StudentAlias"]] = relationship(
        back_populates="student", cascade="all, delete-orphan", lazy="selectin"
    )


class StudentAlias(Base):
    """A player name, as it appears in PGN headers, that identifies a student."""

    __tablename__ = "student_aliases"
    __table_args__ = (UniqueConstraint("student_id", "alias_normalized"),)

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(200))
    alias_normalized: Mapped[str] = mapped_column(String(200), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    student: Mapped[Student] = relationship(back_populates="aliases")


class StudentAccess(Base):
    __tablename__ = "student_access"
    __table_args__ = (UniqueConstraint("user_id", "student_id"),)

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    access_level: Mapped[AccessLevel] = mapped_column(str_enum(AccessLevel, "access_level"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


# --------------------------------------------------------------------------- ingestion


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[uuid.UUID] = _pk()
    original_filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(BigInteger)
    encoding: Mapped[str] = mapped_column(String(32))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    import_status: Mapped[ImportStatus] = mapped_column(
        str_enum(ImportStatus, "import_status"), default=ImportStatus.PENDING
    )
    warnings: Mapped[list[Any]] = mapped_column(default=list)
    import_report: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Game(Base):
    __tablename__ = "games"
    # A game between two coached students is stored once per student (each with its own
    # color), so uniqueness is per student rather than global.
    __table_args__ = (
        UniqueConstraint("student_id", "game_hash", name="uq_games_student_hash"),
        UniqueConstraint(
            "student_id", "source_file_id", "game_index", name="uq_games_student_source_index"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    source_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_files.id"), index=True)
    game_index: Mapped[int] = mapped_column(Integer)
    game_hash: Mapped[str] = mapped_column(String(64), index=True)
    white_name: Mapped[str] = mapped_column(String(200))
    black_name: Mapped[str] = mapped_column(String(200))
    # The student whose import this game belongs to. Whether the student was verified as
    # one of the players is recorded by mapping_status; student_color is set only then.
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    student_color: Mapped[Color | None] = mapped_column(str_enum(Color, "color"))
    mapping_status: Mapped[MappingStatus] = mapped_column(str_enum(MappingStatus, "mapping_status"))
    result: Mapped[GameResult] = mapped_column(str_enum(GameResult, "game_result"))
    played_at: Mapped[date | None] = mapped_column(index=True)  # None if the PGN date is partial
    time_control: Mapped[str | None] = mapped_column(String(50))
    opening_eco: Mapped[str | None] = mapped_column(String(3))
    ply_count: Mapped[int] = mapped_column(Integer)
    has_clock: Mapped[bool] = mapped_column(Boolean, default=False)
    pgn_headers: Mapped[dict[str, Any]] = mapped_column(default=dict)
    raw_pgn: Mapped[str] = mapped_column(Text)
    import_warnings: Mapped[list[Any]] = mapped_column(default=list)
    # Who added this game for this student. Per game, not the file's uploader: identical files
    # are stored once and may be imported for several students by different people. NULL for
    # games imported before this was recorded (not guessed).
    imported_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    source_file: Mapped[SourceFile] = relationship()


# --------------------------------------------------------------------------- analysis


class AnalysisRun(Base):
    """One engine pass over a game. Doubles as the worker job queue."""

    __tablename__ = "analysis_runs"
    __table_args__ = (Index("ix_analysis_runs_status_created", "status", "created_at"),)

    id: Mapped[uuid.UUID] = _pk()
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id"), index=True)
    pass_type: Mapped[AnalysisPass] = mapped_column(
        str_enum(AnalysisPass, "analysis_pass"), default=AnalysisPass.BASELINE
    )
    engine_name: Mapped[str | None] = mapped_column(String(100))
    engine_version: Mapped[str | None] = mapped_column(String(100))
    engine_checksum: Mapped[str | None] = mapped_column(String(64))
    configuration: Mapped[dict[str, Any]] = mapped_column(default=dict)
    analysis_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus, "job_status"), default=JobStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claimed_by: Mapped[str | None] = mapped_column(String(100))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    error_message: Mapped[str | None] = mapped_column(Text)


class MoveAnalysis(Base):
    """Engine evidence for one student decision. All evals are from the student's POV."""

    __tablename__ = "move_analyses"
    __table_args__ = (UniqueConstraint("analysis_run_id", "ply"),)

    id: Mapped[uuid.UUID] = _pk()
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    ply: Mapped[int] = mapped_column(Integer)
    fen_before: Mapped[str] = mapped_column(String(100))
    fen_after: Mapped[str] = mapped_column(String(100))
    uci_move: Mapped[str] = mapped_column(String(5))
    san_move: Mapped[str] = mapped_column(String(10))
    student_move: Mapped[bool] = mapped_column(Boolean)
    phase: Mapped[GamePhase] = mapped_column(str_enum(GamePhase, "game_phase"))
    eval_before_cp: Mapped[int | None] = mapped_column(Integer)
    eval_after_cp: Mapped[int | None] = mapped_column(Integer)
    eval_before_mate: Mapped[int | None] = mapped_column(Integer)
    eval_after_mate: Mapped[int | None] = mapped_column(Integer)
    best_move_uci: Mapped[str | None] = mapped_column(String(5))
    second_best_cp: Mapped[int | None] = mapped_column(Integer)
    principal_variation: Mapped[list[Any]] = mapped_column(default=list)
    best_move_loss_cp: Mapped[int | None] = mapped_column(Integer)
    win_prob_loss: Mapped[float | None] = mapped_column(Float)
    search_depth: Mapped[int | None] = mapped_column(Integer)
    clock_before_ms: Mapped[int | None] = mapped_column(Integer)
    clock_after_ms: Mapped[int | None] = mapped_column(Integer)
    features: Mapped[dict[str, Any]] = mapped_column(default=dict)


# --------------------------------------------------------------------------- weaknesses & profiles


class MistakeAcknowledgement(Base):
    """The student has seen and acknowledged their mistake on this move.

    Keyed by (game, ply), not by observation, so re-analysis and reclassification never lose
    it. Display and coach monitoring only: it does not change any finding or profile.
    """

    __tablename__ = "mistake_acknowledgements"
    __table_args__ = (UniqueConstraint("game_id", "ply", name="uq_mistake_ack_game_ply"),)

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True
    )
    ply: Mapped[int] = mapped_column(Integer)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    acknowledged_at: Mapped[datetime] = mapped_column(default=utcnow)


class WeaknessObservation(Base):
    __tablename__ = "weakness_observations"

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id"), index=True)
    move_analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("move_analyses.id"), index=True)
    skill_code: Mapped[str] = mapped_column(String(64), index=True)
    subskill_code: Mapped[str | None] = mapped_column(String(64))
    evidence_type: Mapped[EvidenceType] = mapped_column(str_enum(EvidenceType, "evidence_type"))
    severity: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    classifier_version: Mapped[str] = mapped_column(String(32))
    taxonomy_version: Mapped[str] = mapped_column(String(32))
    review_status: Mapped[ReviewStatus] = mapped_column(
        str_enum(ReviewStatus, "review_status"), default=ReviewStatus.CANDIDATE
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column()
    review_note: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class SkillOpportunity(Base):
    """A position where a detectable skill was actually tested (e.g. a fork was available
    and needed). Denominator for opportunity-adjusted error rates in profiles."""

    __tablename__ = "skill_opportunities"

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True
    )
    move_analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("move_analyses.id", ondelete="CASCADE"), index=True
    )
    skill_code: Mapped[str] = mapped_column(String(64), index=True)
    subskill_code: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[OpportunityOutcome] = mapped_column(
        str_enum(OpportunityOutcome, "opportunity_outcome")
    )
    classifier_version: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ProfileSnapshot(Base):
    """One versioned profile build for a student. Skill rows hang off it."""

    __tablename__ = "profile_snapshots"
    __table_args__ = (UniqueConstraint("student_id", "profile_version"),)

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    profile_version: Mapped[int] = mapped_column(Integer)
    # Hash of all evidence that went in; an unchanged fingerprint means no new version.
    fingerprint: Mapped[str] = mapped_column(String(64))
    # Only games played before this date were used (research hygiene); None = all games.
    cutoff_date: Mapped[date | None] = mapped_column()
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    triggered_by: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    skills: Mapped[list["StudentSkillProfile"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="StudentSkillProfile.priority_score.desc().nulls_last()",
    )


class StudentSkillProfile(Base):
    """Per-skill aggregate inside a profile snapshot. Historical rows are never modified."""

    __tablename__ = "student_skill_profiles"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "skill_code",
            "subskill_code",
            name="uq_student_skill_profiles_snapshot_skill",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profile_snapshots.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    skill_code: Mapped[str] = mapped_column(String(64), index=True)
    subskill_code: Mapped[str | None] = mapped_column(String(64))
    profile_version: Mapped[int] = mapped_column(Integer)
    state: Mapped[ProfileState] = mapped_column(str_enum(ProfileState, "profile_state"))
    error_rate: Mapped[float | None] = mapped_column(Float)  # smoothed (Beta-Binomial)
    opportunity_count: Mapped[int | None] = mapped_column(Integer)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    games_affected: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float | None] = mapped_column(Float)
    priority_score: Mapped[float | None] = mapped_column(Float)
    evidence_summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    generated_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    snapshot: Mapped[ProfileSnapshot] = relationship(back_populates="skills")


class LearningPlan(TimestampMixin, Base):
    __tablename__ = "learning_plans"

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    profile_version: Mapped[int | None] = mapped_column(Integer)
    objective: Mapped[str] = mapped_column(Text)
    weekly_goals: Mapped[list[Any]] = mapped_column(default=list)
    recommended_skills: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[PlanStatus] = mapped_column(
        str_enum(PlanStatus, "plan_status"), default=PlanStatus.DRAFT
    )


# --------------------------------------------------------------------------- coaching & exercises


class CoachingSession(Base):
    __tablename__ = "coaching_sessions"

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    learning_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("learning_plans.id"))
    model_provider: Mapped[str] = mapped_column(String(64))
    model_id: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    evidence_references: Mapped[list[Any]] = mapped_column(default=list)
    request_metadata: Mapped[dict[str, Any]] = mapped_column(default=dict)
    response_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    validation_status: Mapped[ValidationStatus] = mapped_column(
        str_enum(ValidationStatus, "validation_status"), default=ValidationStatus.PENDING
    )
    validation_errors: Mapped[list[Any]] = mapped_column(default=list)
    token_usage: Mapped[dict[str, Any]] = mapped_column(default=dict)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    skill_code: Mapped[str] = mapped_column(String(64), index=True)
    subskill_code: Mapped[str | None] = mapped_column(String(64))
    purpose: Mapped[ExercisePurpose] = mapped_column(str_enum(ExercisePurpose, "exercise_purpose"))
    status: Mapped[ExerciseStatus] = mapped_column(
        str_enum(ExerciseStatus, "exercise_status"), default=ExerciseStatus.OPEN, index=True
    )
    source_game_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("games.id"))
    source_move_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("move_analyses.id")
    )
    start_fen: Mapped[str] = mapped_column(String(100))
    accepted_moves: Mapped[list[Any]] = mapped_column(default=list)  # UCI; hidden until done
    solution_source: Mapped[str] = mapped_column(String(64))
    validation_status: Mapped[ValidationStatus] = mapped_column(
        str_enum(ValidationStatus, "validation_status"), default=ValidationStatus.PENDING
    )
    difficulty: Mapped[str | None] = mapped_column(String(32))
    explanation: Mapped[str | None] = mapped_column(Text)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    hints_given: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column()


class ExerciseAttempt(Base):
    __tablename__ = "exercise_attempts"

    id: Mapped[uuid.UUID] = _pk()
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    submitted_move: Mapped[str] = mapped_column(String(5))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    time_taken_ms: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


# --------------------------------------------------------------------------- puzzles


class Puzzle(Base):
    """A puzzle from the Lichess puzzle database (CC0). Imported, never edited.

    `fen` is the position BEFORE the opponent's move; `moves` (UCI, space separated) starts
    with that opponent move, and the student's solution begins with the second move.
    """

    __tablename__ = "puzzles"

    id: Mapped[uuid.UUID] = _pk()
    lichess_id: Mapped[str] = mapped_column(String(16), unique=True)
    fen: Mapped[str] = mapped_column(String(100))
    moves: Mapped[str] = mapped_column(Text)
    rating: Mapped[int] = mapped_column(Integer, index=True)
    rating_deviation: Mapped[int] = mapped_column(Integer)
    popularity: Mapped[int] = mapped_column(Integer)
    nb_plays: Mapped[int] = mapped_column(Integer)
    themes: Mapped[list[Any]] = mapped_column(default=list)
    opening_tags: Mapped[list[Any]] = mapped_column(default=list)
    game_ref: Mapped[str | None] = mapped_column(String(64))  # Lichess game id (and ply)
    source: Mapped[str] = mapped_column(String(128))  # dataset and revision it came from
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PuzzleTheme(Base):
    """One row per (puzzle, theme), with the rating copied for fast "theme near rating" lookups."""

    __tablename__ = "puzzle_themes"
    __table_args__ = (Index("ix_puzzle_themes_theme_rating", "theme", "rating"),)

    puzzle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("puzzles.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(String(48), primary_key=True)
    rating: Mapped[int] = mapped_column(Integer)


class PuzzleAssignment(Base):
    """One puzzle given to a student, as part of a set of (usually) four of rising rating."""

    __tablename__ = "puzzle_assignments"
    __table_args__ = (
        UniqueConstraint("student_id", "puzzle_id", name="uq_puzzle_assignment_student_puzzle"),
    )

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    puzzle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("puzzles.id"), index=True)
    set_id: Mapped[uuid.UUID] = mapped_column(index=True)
    position: Mapped[int] = mapped_column(Integer)  # 1..n within the set, easiest first
    skill_code: Mapped[str] = mapped_column(String(64), index=True)
    subskill_code: Mapped[str | None] = mapped_column(String(64))
    theme: Mapped[str] = mapped_column(String(48))  # the theme it was selected for
    source_game_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL")
    )
    source_ply: Mapped[int | None] = mapped_column(Integer)  # the mistake it trains
    target_rating: Mapped[int] = mapped_column(Integer)
    student_rating_before: Mapped[float] = mapped_column(Float)
    progress: Mapped[int] = mapped_column(Integer, default=1)  # plies of `moves` played
    status: Mapped[PuzzleStatus] = mapped_column(
        str_enum(PuzzleStatus, "puzzle_status"), default=PuzzleStatus.OPEN
    )
    result: Mapped[PuzzleResult | None] = mapped_column(str_enum(PuzzleResult, "puzzle_result"))
    wrong_moves: Mapped[int] = mapped_column(Integer, default=0)
    selection_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column()

    puzzle: Mapped[Puzzle] = relationship()


class StudentPuzzleRating(Base):
    """The student's puzzle rating for one skill, updated after every decided puzzle."""

    __tablename__ = "student_puzzle_ratings"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "skill_code", "subskill_code", name="uq_student_puzzle_rating_skill"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    skill_code: Mapped[str] = mapped_column(String(64))
    subskill_code: Mapped[str | None] = mapped_column(String(64))
    rating: Mapped[float] = mapped_column(Float)
    puzzles_decided: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _pk()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
