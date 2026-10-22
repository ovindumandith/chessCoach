import os
import uuid
from pathlib import Path

# Configure a safe test environment before any chesscoach import reads settings.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite://"
# Never call a real LLM from tests, even when .env holds a key (environment variables take
# precedence over .env): tests use mock providers, and a live call would cost money.
os.environ["LLM_ENABLED"] = "false"
os.environ["LLM_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from chesscoach.core.config import Settings, get_settings  # noqa: E402

# Tests never read the developer's .env (keys, models, URLs): only defaults and what each
# test sets explicitly. The one exception is the local Stockfish path, so the optional
# engine tests (@pytest.mark.engine) still run where Stockfish is installed.
if "STOCKFISH_PATH" not in os.environ:
    from dotenv import dotenv_values

    _stockfish = dotenv_values(Path(__file__).parents[1] / ".env").get("STOCKFISH_PATH")
    if _stockfish:
        os.environ["STOCKFISH_PATH"] = _stockfish
Settings.model_config["env_file"] = None
from chesscoach.db.enums import AccessLevel, UserRole  # noqa: E402
from chesscoach.db.models import Base, Game, StudentAccess, User  # noqa: E402
from chesscoach.db.session import get_db, make_engine  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def engine():
    eng = make_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(eng)  # tests only; real deployments use Alembic
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Session:
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture
def storage_dir(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "uploads"
    monkeypatch.setenv("STORAGE_DIR", str(path))
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
def client(engine, storage_dir) -> TestClient:
    from chesscoach.api.main import create_app

    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def _get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = _get_db
    session = factory()
    with TestClient(app) as c:
        c.as_student = Learner(session)  # headers for acting as the student (see Learner)
        # Administrators label findings for research (confirm/reject/correct).
        session.add(User(email="admin@test.local", role=UserRole.ADMIN))
        session.commit()
        c.as_admin = {"X-Dev-User-Email": "admin@test.local"}
        yield c
    session.close()


@pytest.fixture
def make_user(db):
    def _make(email: str, role: UserRole = UserRole.COACH) -> User:
        user = User(email=email, role=role)
        db.add(user)
        db.commit()
        return user

    return _make


class Learner:
    """Request headers for a student's OWN login (SELF access): students add and analyze
    games, get lessons and create exercises; coaches only monitor. Reuses the student's
    existing login, or creates one on first use."""

    def __init__(self, db: Session):
        self.db = db

    def __call__(self, student_id) -> dict:
        sid = uuid.UUID(str(student_id))
        user = self.db.scalar(
            select(User)
            .join(StudentAccess, StudentAccess.user_id == User.id)
            .where(StudentAccess.student_id == sid, StudentAccess.access_level == AccessLevel.SELF)
        )
        if user is None:
            user = User(email=f"learner-{sid.hex[:12]}@test.local", role=UserRole.STUDENT)
            self.db.add(user)
            self.db.flush()
            self.db.add(
                StudentAccess(user_id=user.id, student_id=sid, access_level=AccessLevel.SELF)
            )
            self.db.commit()
        return {"X-Dev-User-Email": user.email}

    def game(self, game_id) -> dict:
        """Headers for the student who owns this game."""
        return self(self.db.get(Game, uuid.UUID(str(game_id))).student_id)


@pytest.fixture
def mixed_pgn() -> bytes:
    return (FIXTURES / "mixed_games.pgn").read_bytes()


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from chesscoach.core.ratelimit import limiter

    limiter.reset()
    yield
    limiter.reset()
