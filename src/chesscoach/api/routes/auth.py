import uuid

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from chesscoach import accounts
from chesscoach.api.deps import CurrentUser, DbSession, client_ip
from chesscoach.core.config import get_settings
from chesscoach.db.enums import UserRole

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole


class TokenOut(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user: UserOut


class MeOut(UserOut):
    students: list[dict]


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class UserCreate(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)
    role: UserRole


class StudentAccountCreate(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


def _user(u) -> UserOut:
    return UserOut(id=u.id, email=u.email, role=u.role)


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginRequest, request: Request, db: DbSession) -> TokenOut:
    result = accounts.login(
        db, get_settings(), email=body.email, password=body.password, ip=client_ip(request)
    )
    return TokenOut(**{**result, "user": _user(result["user"])})


@router.get("/auth/me", response_model=MeOut)
def me(db: DbSession, user: CurrentUser) -> MeOut:
    return MeOut(**_user(user).model_dump(), students=accounts.accessible_students(db, user))


@router.post("/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChange, db: DbSession, user: CurrentUser) -> None:
    accounts.change_password(db, user, current=body.current_password, new=body.new_password)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: DbSession, user: CurrentUser) -> UserOut:
    """Admins create coach or admin accounts."""
    return _user(
        accounts.create_user(db, user, email=body.email, password=body.password, role=body.role)
    )


@router.post(
    "/students/{student_id}/account", response_model=UserOut, status_code=status.HTTP_201_CREATED
)
def create_student_account(
    student_id: uuid.UUID, body: StudentAccountCreate, db: DbSession, user: CurrentUser
) -> UserOut:
    """A coach creates a login for one of their students (access to their own record only)."""
    return _user(
        accounts.create_student_account(
            db, user, student_id, email=body.email, password=body.password
        )
    )
