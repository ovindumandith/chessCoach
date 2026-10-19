"""Student management service."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chesscoach.core.access import require_coach_role, require_student_access
from chesscoach.core.audit import record_audit
from chesscoach.core.errors import ConflictError
from chesscoach.db.enums import AccessLevel, UserRole
from chesscoach.db.models import Student, StudentAccess, StudentAlias, User
from chesscoach.ingestion.pgn_parser import normalize_name


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


def _dedupe_aliases(aliases: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for alias in aliases:
        n = normalize_name(alias)
        if n and n not in seen:
            seen.add(n)
            result.append(alias.strip())
    return result
