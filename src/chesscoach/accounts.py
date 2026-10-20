"""Account service: login, password changes, and creating coach/student accounts."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.core.access import require_student_access
from chesscoach.core.audit import record_audit
from chesscoach.core.config import Settings
from chesscoach.core.errors import ConflictError, DomainError, ForbiddenError, ValidationFailedError
from chesscoach.core.ratelimit import limiter
from chesscoach.core.security import (
    create_access_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from chesscoach.db.enums import AccessLevel, UserRole
from chesscoach.db.models import StudentAccess, User

# Compared against when the email is unknown, so response time does not reveal which
# emails have accounts.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


class AuthenticationError(DomainError):
    status_code = 401
    code = "invalid_credentials"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def login(db: Session, settings: Settings, *, email: str, password: str, ip: str) -> dict:
    email = normalize_email(email)
    limiter.hit(
        f"login:{email}:{ip}", limit=settings.rate_limit_logins_per_15min, window_seconds=900
    )
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if not (user and ok and user.is_active):
        record_audit(
            db,
            actor_user_id=user.id if user else None,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id if user else None,
            details={"ip": ip},
        )
        db.commit()
        raise AuthenticationError("Invalid email or password")
    token, expires_in = create_access_token(settings, user.id, user.role.value)
    record_audit(
        db,
        actor_user_id=user.id,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        details={"ip": ip},
    )
    db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_in": expires_in, "user": user}


def change_password(db: Session, user: User, *, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise AuthenticationError("Current password is incorrect")
    _set_password(user, new)
    record_audit(
        db,
        actor_user_id=user.id,
        action="auth.password_change",
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()


def create_user(
    db: Session, actor: User | None, *, email: str, password: str, role: UserRole
) -> User:
    """Admins create coach/admin accounts (actor None = bootstrap CLI)."""
    if actor is not None and actor.role != UserRole.ADMIN:
        raise ForbiddenError("Only administrators can create coach or admin accounts")
    if role == UserRole.STUDENT:
        raise ValidationFailedError("Create student accounts from the student's page")
    user = _new_user(db, email, password, role)
    record_audit(
        db,
        actor_user_id=actor.id if actor else None,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        details={"role": role.value},
    )
    db.commit()
    return user


def create_student_account(
    db: Session, coach: User, student_id: uuid.UUID, *, email: str, password: str
) -> User:
    """A coach gives one of their students a login with access to only their own record."""
    require_student_access(db, coach, student_id, coach_only=True)
    existing_self = db.scalar(
        select(StudentAccess).where(
            StudentAccess.student_id == student_id, StudentAccess.access_level == AccessLevel.SELF
        )
    )
    if existing_self is not None:
        raise ConflictError("This student already has an account")
    user = _new_user(db, email, password, UserRole.STUDENT)
    db.add(StudentAccess(user_id=user.id, student_id=student_id, access_level=AccessLevel.SELF))
    record_audit(
        db,
        actor_user_id=coach.id,
        action="student.account_create",
        entity_type="student",
        entity_id=student_id,
        details={"user_id": str(user.id)},
    )
    db.commit()
    return user


def accessible_students(db: Session, user: User) -> list[dict]:
    rows = db.execute(
        select(StudentAccess.student_id, StudentAccess.access_level).where(
            StudentAccess.user_id == user.id
        )
    ).all()
    return [{"student_id": str(sid), "access_level": level.value} for sid, level in rows]


def _new_user(db: Session, email: str, password: str, role: UserRole) -> User:
    email = normalize_email(email)
    if "@" not in email:
        raise ValidationFailedError("A valid email is required")
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise ConflictError("An account with this email already exists")
    user = User(email=email, role=role)
    _set_password(user, password)
    db.add(user)
    db.flush()
    return user


def _set_password(user: User, password: str) -> None:
    try:
        validate_password_strength(password)
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc
    user.password_hash = hash_password(password)
