"""Experiment configuration and reproducible result records (project.md §27)."""

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from chesscoach.analysis.game_analyzer import ANALYSIS_VERSION
from chesscoach.analysis.phase import PHASE_RULES_VERSION
from chesscoach.analysis.scores import SCORES_VERSION
from chesscoach.classification.classifier import CLASSIFIER_VERSION
from chesscoach.classification.motifs import MOTIFS_VERSION
from chesscoach.classification.taxonomy import get_taxonomy
from chesscoach.coaching.fallback import TEMPLATE_VERSION
from chesscoach.coaching.service import PROMPT_VERSION
from chesscoach.core.config import get_settings
from chesscoach.db.types import utcnow
from chesscoach.exercises.selection import SELECTION_VERSION
from chesscoach.profiling.aggregator import PROFILE_VERSION

SECRET_SETTINGS = {"app_secret_key", "llm_api_key", "database_url"}


@dataclass
class ExperimentConfig:
    name: str
    seed: int = 7
    student_ids: list[str] | None = None  # None = every student
    cutoff_date: date | None = None
    k: int = 3
    min_games_before: int = 3
    min_games_after: int = 2
    sample_flagged: int = 100
    sample_unflagged: int = 100
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "ExperimentConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        known = {k: data.pop(k) for k in list(data) if k in cls.__dataclass_fields__}
        if isinstance(known.get("cutoff_date"), str):
            known["cutoff_date"] = date.fromisoformat(known["cutoff_date"])
        return cls(**known, extra=data)


def versions() -> dict:
    return {
        "analysis": ANALYSIS_VERSION,
        "scores": SCORES_VERSION,
        "phase_rules": PHASE_RULES_VERSION,
        "classifier": CLASSIFIER_VERSION,
        "motifs": MOTIFS_VERSION,
        "taxonomy": get_taxonomy().version,
        "profile": PROFILE_VERSION,
        "prompt": PROMPT_VERSION,
        "template": TEMPLATE_VERSION,
        "exercise_selection": SELECTION_VERSION,
    }


def git_revision() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=5
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        return f"{sha}{'-dirty' if dirty else ''}"
    except (OSError, subprocess.SubprocessError):
        # No git inside containers: pass the revision at build or run time instead.
        return os.environ.get("CHESSCOACH_REVISION", "unknown")


def results_dir() -> Path:
    return get_settings().experiments_dir


def record(
    study: str, config: ExperimentConfig, dataset: dict, results: dict, out_dir: Path | None = None
) -> Path:
    """Write a self-describing result file and return its path."""
    out_dir = out_dir or results_dir()
    settings = {
        k: v for k, v in get_settings().model_dump(mode="json").items() if k not in SECRET_SETTINGS
    }
    payload = {
        "study": study,
        "experiment": config.name,
        "created_at": utcnow().isoformat(),
        "code_revision": git_revision(),
        "versions": versions(),
        "config": {**{k: v for k, v in config.__dict__.items() if k != "extra"}, **config.extra},
        "settings": settings,
        "dataset": dataset,
        "results": results,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{config.name}-{study}-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
