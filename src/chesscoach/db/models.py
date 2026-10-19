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
    GamePhase,
    GameResult,
    ImportStatus,
    JobStatus,
    MappingStatus,
    PlanStatus,
    ProfileState,
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


class StudentSkillProfile(Base):
    __tablename__ = "student_skill_profiles"
    __table_args__ = (UniqueConstraint("student_id", "skill_code", "profile_version"),)

    id: Mapped[uuid.UUID] = _pk()
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    skill_code: Mapped[str] = mapped_column(String(64), index=True)
    profile_version: Mapped[int] = mapped_column(Integer)
    state: Mapped[ProfileState] = mapped_column(str_enum(ProfileState, "profile_state"))
    error_rate: Mapped[float | None] = mapped_column(Float)
    opportunity_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    games_affected: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float | None] = mapped_column(Float)
    priority_score: Mapped[float | None] = mapped_column(Float)
    evidence_summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    generated_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


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
    source_game_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("games.id"))
    source_move_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("move_analyses.id")
    )
    start_fen: Mapped[str] = mapped_column(String(100))
    accepted_moves: Mapped[list[Any]] = mapped_column(default=list)
    solution_source: Mapped[str] = mapped_column(String(64))
    validation_status: Mapped[ValidationStatus] = mapped_column(
        str_enum(ValidationStatus, "validation_status"), default=ValidationStatus.PENDING
    )
    difficulty: Mapped[str | None] = mapped_column(String(32))
    explanation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


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
    is_correct: Mapped[bool] = mapped_column(Boolean)
    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    time_taken_ms: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _pk()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
