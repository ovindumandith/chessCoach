"""Student management service."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chesscoach.core.access import require_coach_role, require_student_access
from chesscoach.core.audit import record_audit
from chesscoach.core.errors import ConflictError
from chesscoach.db.enums import AccessLevel, UserRole
from chesscoach.db.models import (
    Game,
    Student,
    StudentAccess,
    StudentAlias,
    User,
)
from chesscoach.ingestion.pgn_parser import normalize_name
from chesscoach.mistakes import open_mistake_counts


def create_student(
    db: Session,
    user: User,
    *,
    display_name: str,
    aliases: list[str],
    rating_estimate: int | None = None,
    rating_source: str | None = None,
    skill_level: str | None = None,
    learning_preferences: dict | None = None,
) -> Student:
    require_coach_role(user)
    student = Student(
        display_name=display_name.strip(),
        rating_estimate=rating_estimate,
        rating_source=rating_source,
        skill_level=skill_level,
        learning_preferences=learning_preferences or {},
    )
    db.add(student)
    db.flush()
    for alias in _dedupe_aliases(aliases):
        student.aliases.append(StudentAlias(alias=alias, alias_normalized=normalize_name(alias)))
    db.add(StudentAccess(user_id=user.id, student_id=student.id, access_level=AccessLevel.COACH))
    record_audit(
        db,
        actor_user_id=user.id,
        action="student.create",
        entity_type="student",
        entity_id=student.id,
        details={"alias_count": len(student.aliases)},
    )
    db.commit()
    return student


def add_alias(db: Session, user: User, student_id: uuid.UUID, alias: str) -> Student:
    student = require_student_access(db, user, student_id, coach_only=True)
    normalized = normalize_name(alias)
    if not normalized:
        raise ConflictError("Alias cannot be empty")
    if any(a.alias_normalized == normalized for a in student.aliases):
        raise ConflictError("Alias already exists for this student")
    student.aliases.append(StudentAlias(alias=alias.strip(), alias_normalized=normalized))
    record_audit(
        db,
        actor_user_id=user.id,
        action="student.alias_add",
        entity_type="student",
        entity_id=student.id,
    )
    db.commit()
    return student


def list_students(db: Session, user: User, *, limit: int, offset: int) -> tuple[list[Student], int]:
    query = select(Student)
    if user.role != UserRole.ADMIN:
        query = query.join(StudentAccess, StudentAccess.student_id == Student.id).where(
            StudentAccess.user_id == user.id
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(Student.display_name, Student.id).limit(limit).offset(offset)
    ).all()
    return list(rows), total


def student_activity(db: Session, student_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Per-student counts for the coach's overview. Callers have already checked access
    (the ids come from `list_students`)."""
    if not student_ids:
        return {}
    out = {
        sid: {
            "games": 0,
            "games_by_student": 0,
            "last_student_upload": None,
            "mistakes": 0,
            "open_mistakes": 0,
            "has_login": False,
        }
        for sid in student_ids
    }
    for sid, n in db.execute(
        select(Game.student_id, func.count())
        .where(Game.student_id.in_(student_ids))
        .group_by(Game.student_id)
    ):
        out[sid]["games"] = n
    # Games the student added themself: imported by a user holding SELF access to that record.
    for sid, n, last in db.execute(
        select(Game.student_id, func.count(), func.max(Game.created_at))
        .join(
            StudentAccess,
            (StudentAccess.user_id == Game.imported_by)
            & (StudentAccess.student_id == Game.student_id)
            & (StudentAccess.access_level == AccessLevel.SELF),
        )
        .where(Game.student_id.in_(student_ids))
        .group_by(Game.student_id)
    ):
        out[sid]["games_by_student"] = n
        out[sid]["last_student_upload"] = last
    for sid, c in open_mistake_counts(db, student_ids).items():
        out[sid]["mistakes"] = c["mistakes"]
        out[sid]["open_mistakes"] = c["mistakes"] - c["acknowledged"]
    for (sid,) in db.execute(
        select(StudentAccess.student_id).where(
            StudentAccess.student_id.in_(student_ids),
            StudentAccess.access_level == AccessLevel.SELF,
        )
    ):
        out[sid]["has_login"] = True
    return out


def _dedupe_aliases(aliases: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for alias in aliases:
        n = normalize_name(alias)
        if n and n not in seen:
            seen.add(n)
            result.append(alias.strip())
    return result
