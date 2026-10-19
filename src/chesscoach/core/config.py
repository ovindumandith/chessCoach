"""Typed application settings loaded from environment variables / `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_secret_key: str = "replace_me"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./data/chesscoach.db"

    stockfish_path: str = "/usr/games/stockfish"
    stockfish_depth: int = Field(default=16, ge=1, le=60)
    stockfish_threads: int = Field(default=2, ge=1)
    stockfish_hash_mb: int = Field(default=512, ge=16)

    llm_provider: str = "openai_compatible"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""

    storage_dir: Path = Path("./data/uploads")
    pgn_max_upload_mb: int = Field(default=25, ge=1)

    analysis_max_concurrent_games: int = Field(default=2, ge=1)

    @property
    def pgn_max_upload_bytes(self) -> int:
        return self.pgn_max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
