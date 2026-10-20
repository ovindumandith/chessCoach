"""Shared FastAPI dependencies: authentication and rate limits.

Authentication is a JWT Bearer token (`POST /api/v1/auth/login`). The development header
stub (`X-Dev-User-Email`) is accepted only when `Settings.dev_auth_allowed` is true: the
test environment, or development with AUTH_DEV_BYPASS=true. Authorization (who may see
which student) is enforced in the service layer through `student_access`.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.core.config import Settings, get_settings
from chesscoach.core.ratelimit import limiter
from chesscoach.core.security import decode_access_token
from chesscoach.db.enums import UserRole
from chesscoach.db.models import User
from chesscoach.db.session import get_db

DEV_COACH_EMAIL = "dev-coach@chesscoach.local"

DbSession = Annotated[Session, Depends(get_db)]


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user_email: Annotated[str | None, Header()] = None,
) -> User:
    settings = get_settings()
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise _unauthorized()
        user_id = decode_access_token(settings, token)
        user = db.get(User, user_id) if user_id else None
        if user is None:
            raise _unauthorized("Invalid or expired token")
    elif settings.dev_auth_allowed:
        user = _dev_user(db, x_dev_user_email)
    else:
        raise _unauthorized()
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is inactive")
    return user


def _dev_user(db: Session, header_email: str | None) -> User:
    email = (header_email or DEV_COACH_EMAIL).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        if email != DEV_COACH_EMAIL:
            raise _unauthorized("Unknown development user")
        user = User(email=email, role=UserRole.COACH)
        db.add(user)
        db.commit()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def rate_limited(name: str, per_hour: Callable[[Settings], int]):
    """Dependency enforcing a per-user hourly limit on an expensive route."""

    def dependency(user: CurrentUser) -> None:
        limiter.hit(f"{name}:{user.id}", limit=per_hour(get_settings()), window_seconds=3600)

    return Depends(dependency)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
