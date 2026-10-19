"""Portable column types so the same models run on PostgreSQL and SQLite."""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Enum, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB

# JSON on SQLite, JSONB on PostgreSQL.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetime. SQLite drops tzinfo, so it is restored on read."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Naive datetimes are not allowed; use UTC-aware values")
            value = value.astimezone(UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


def str_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """String-backed enum column with a CHECK constraint (no native PG enum types)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )
