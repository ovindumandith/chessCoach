"""Shared FastAPI dependencies.

Authentication is a development stub until Phase 8. It resolves (or creates) a single
dev coach account and refuses to run in production. Authorization (student_access
checks) is real and enforced in the service layer from day one.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.core.config import get_settings
from chesscoach.db.enums import UserRole
from chesscoach.db.models import User
from chesscoach.db.session import get_db

DEV_COACH_EMAIL = "dev-coach@chesscoach.local"

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    x_dev_user_email: Annotated[str | None, Header()] = None,
) -> User:
    if get_settings().is_production:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "Authentication is not configured for production"
        )
    email = (x_dev_user_email or DEV_COACH_EMAIL).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        if email != DEV_COACH_EMAIL:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown development user")
        user = User(email=email, role=UserRole.COACH)
        db.add(user)
        db.commit()
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
