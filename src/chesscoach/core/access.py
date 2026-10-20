"""Per-student authorization. Every student-scoped service call goes through here."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.core.errors import ForbiddenError, NotFoundError
from chesscoach.db.enums import AccessLevel, UserRole
from chesscoach.db.models import Student, StudentAccess, User


def get_access_level(db: Session, user: User, student_id: uuid.UUID) -> AccessLevel | None:
    return db.scalar(
        select(StudentAccess.access_level).where(
            StudentAccess.user_id == user.id, StudentAccess.student_id == student_id
        )
    )


def require_student_access(
    db: Session, user: User, student_id: uuid.UUID, *, coach_only: bool = False
) -> Student:
    """Return the student if `user` may access it; raise otherwise.

    Admins can access everything. Coaches need a `coach` access row. Students need a
    `self` access row and are refused coach-only operations.
    """
    student = db.get(Student, student_id)
    if student is None:
        raise NotFoundError("Student not found")
    if user.role == UserRole.ADMIN:
        return student
    level = get_access_level(db, user, student_id)
    if level is None:
        raise ForbiddenError("You do not have access to this student")
    if coach_only and level != AccessLevel.COACH:
        raise ForbiddenError("This action requires coach access")
    return student


def require_coach_role(user: User) -> None:
    if user.role not in (UserRole.COACH, UserRole.ADMIN):
        raise ForbiddenError("This action requires a coach account")


def require_own_student_record(db: Session, user: User, student_id: uuid.UUID) -> Student:
    """Only the student's own account may act as the student (e.g. answer exercises), so
    coach activity never pollutes the student's performance data."""
    student = require_student_access(db, user, student_id)
    if get_access_level(db, user, student_id) != AccessLevel.SELF:
        raise ForbiddenError("Only the student's own account can do this")
    return student
