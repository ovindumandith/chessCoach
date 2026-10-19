"""Pydantic request/response models for the public API."""

import uuid
from datetime import date, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from chesscoach.db.enums import Color, GameResult, MappingStatus


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
