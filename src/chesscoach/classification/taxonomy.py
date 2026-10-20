"""Load and validate the versioned skill taxonomy (config/skill_taxonomy.yaml)."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from chesscoach.core.config import get_settings

UNCLASSIFIED = "unclassified"
INSUFFICIENT_EVIDENCE = "insufficient_evidence"

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "skill_taxonomy.yaml"


class Subskill(BaseModel):
    name: str
    auto: bool = False


class Category(BaseModel):
    name: str
    subskills: dict[str, Subskill] = Field(default_factory=dict)


class Special(BaseModel):
    name: str
    description: str = ""


class Taxonomy(BaseModel):
    version: str
    special: dict[str, Special]
    categories: dict[str, Category]

    def is_valid(self, skill_code: str, subskill_code: str | None = None) -> bool:
        if skill_code in self.special:
            return subskill_code is None
        category = self.categories.get(skill_code)
        if category is None:
            return False
        return subskill_code is None or subskill_code in category.subskills

    def require_valid(self, skill_code: str, subskill_code: str | None = None) -> None:
        if not self.is_valid(skill_code, subskill_code):
            label = f"{skill_code}.{subskill_code}" if subskill_code else skill_code
            raise ValueError(f"Unknown taxonomy code: {label}")


def load_taxonomy(path: Path = DEFAULT_PATH) -> Taxonomy:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    taxonomy = Taxonomy.model_validate(data)
    for required in (UNCLASSIFIED, INSUFFICIENT_EVIDENCE):
        if required not in taxonomy.special:
            raise ValueError(f"Taxonomy must define special code {required!r}")
    return taxonomy


@lru_cache
def get_taxonomy() -> Taxonomy:
    configured = get_settings().taxonomy_path
    return load_taxonomy(configured if configured.is_file() else DEFAULT_PATH)
