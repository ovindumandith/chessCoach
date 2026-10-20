import os
from pathlib import Path

# Configure a safe test environment before any chesscoach import reads settings.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite://"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from chesscoach.core.config import get_settings  # noqa: E402
from chesscoach.db.enums import UserRole  # noqa: E402
from chesscoach.db.models import Base, User  # noqa: E402
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
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_user(db):
    def _make(email: str, role: UserRole = UserRole.COACH) -> User:
        user = User(email=email, role=role)
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture
def mixed_pgn() -> bytes:
    return (FIXTURES / "mixed_games.pgn").read_bytes()


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from chesscoach.core.ratelimit import limiter

    limiter.reset()
    yield
    limiter.reset()
