"""Typed application settings loaded from environment variables / `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_secret_key: str = "replace_me"  # signs JWTs; must be strong outside dev/test
    log_level: str = "INFO"

    # Authentication. The development header stub (X-Dev-User-Email) works only in the
    # test environment, or in development when auth_dev_bypass is explicitly enabled.
    auth_dev_bypass: bool = False
    access_token_minutes: int = Field(default=60, ge=5, le=24 * 60)
    cors_origins: list[str] = ["http://localhost:5173"]

    # Rate limits (per user, per hour) for expensive operations; login is per email+IP.
    rate_limit_lessons_per_hour: int = Field(default=20, ge=1)
    rate_limit_analysis_per_hour: int = Field(default=120, ge=1)
    rate_limit_exercises_per_hour: int = Field(default=60, ge=1)
    rate_limit_imports_per_hour: int = Field(default=60, ge=1)
    rate_limit_logins_per_15min: int = Field(default=10, ge=1)

    database_url: str = "sqlite:///./data/chesscoach.db"

    stockfish_path: str = "/usr/games/stockfish"
    stockfish_depth: int = Field(default=16, ge=1, le=60)
    stockfish_threads: int = Field(default=1, ge=1)  # >1 makes search non-deterministic
    stockfish_hash_mb: int = Field(default=512, ge=16)
    # Pass 2: deeper re-analysis of critical positions.
    stockfish_critical_depth: int = Field(default=22, ge=1, le=60)
    analysis_multipv: int = Field(default=2, ge=1, le=5)
    # A student move is "critical" if it loses at least this much win probability (0-1),
    # or involves a mate transition.
    analysis_critical_wp_loss: float = Field(default=0.10, ge=0.0, le=1.0)
    analysis_critical_enabled: bool = True
    analysis_max_attempts: int = Field(default=3, ge=1)
    worker_poll_seconds: float = Field(default=2.0, gt=0)
    # A running job not finished within this time is assumed abandoned (worker crash).
    worker_stale_after_seconds: int = Field(default=1800, ge=60)

    # LLM calls are opt-in: with llm_enabled=False every lesson uses the deterministic
    # template fallback, so tests and keyless setups never touch the network.
    llm_enabled: bool = False
    llm_provider: Literal["anthropic", "openai_compatible"] = "anthropic"
    # Anthropic: empty key lets the SDK resolve credentials (ANTHROPIC_API_KEY or profile).
    llm_api_key: str = ""
    llm_base_url: str = ""  # required for openai_compatible
    llm_model: str = "claude-opus-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_max_tokens: int = Field(default=16000, ge=1000)
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)  # transport retries (429/5xx/network)
    llm_validation_retries: int = Field(default=1, ge=0)  # regenerate after failed checks

    storage_dir: Path = Path("./data/uploads")
    pgn_max_upload_mb: int = Field(default=25, ge=1)

    # Relative paths resolve against the working directory (repo root locally, /app in Docker).
    taxonomy_path: Path = Path("config/skill_taxonomy.yaml")
    experiments_dir: Path = Path("data/experiments")  # research result records

    analysis_max_concurrent_games: int = Field(default=2, ge=1)

    @property
    def pgn_max_upload_bytes(self) -> int:
        return self.pgn_max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def dev_auth_allowed(self) -> bool:
        return self.app_env == "test" or (self.app_env == "development" and self.auth_dev_bypass)

    def check_security(self) -> None:
        """Refuse to run outside dev/test with an unsafe signing key."""
        if self.app_env == "production" and (
            self.app_secret_key in ("", "replace_me") or len(self.app_secret_key) < 32
        ):
            raise RuntimeError(
                "APP_SECRET_KEY must be a random string of 32+ characters in production"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
