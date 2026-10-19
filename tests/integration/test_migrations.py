"""Alembic migrations must build the full schema and stay in sync with the models."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from chesscoach.db.models import Base

ROOT = Path(__file__).resolve().parents[2]


def _config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_downgrade_and_no_drift(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    cfg = _config(url)
    command.upgrade(cfg, "head")

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert set(Base.metadata.tables) <= tables

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Models and migrations differ: {diff}"

    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()
