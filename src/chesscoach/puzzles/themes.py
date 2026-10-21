"""The versioned mapping from skills (config/skill_taxonomy.yaml) to Lichess puzzle themes."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from chesscoach.classification.taxonomy import UNCLASSIFIED, get_taxonomy

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "puzzle_themes.yaml"

# Every theme key Lichess uses (lichess-org/lila translation/source/puzzleTheme.xml).
LICHESS_THEMES = frozenset(
    """advancedPawn advantage anastasiaMate arabianMate attackingF2F7 attraction backRankMate
    balestraMate blindSwineMate bishopEndgame bodenMate castling enPassant capturingDefender
    collinearMove cornerMate crushing discoveredCheck doubleBishopMate dovetailMate equality
    kingsideAttack clearance defensiveMove deflection discoveredAttack doubleCheck endgame
    epauletteMate exposedKing fork hangingPiece hookMate interference intermezzo killBoxMate
    pillsburysMate morphysMate swallowstailMate triangleMate vukovicMate knightEndgame long
    master masterVsMaster mate mateIn1 mateIn2 mateIn3 mateIn4 mateIn5 middlegame oneMove
    opening operaMate pawnEndgame pin promotion promotePawnToQueenRookOrMinor queenEndgame
    queenRookEndgame queensideAttack quietMove rookEndgame sacrifice short skewer
    smotheredMate superGM trappedPiece underPromotion veryLong xRayAttack zugzwang""".split()
)


@dataclass(frozen=True)
class ThemeMap:
    version: str
    skills: dict[tuple[str, str | None], tuple[str, ...]]
    phases: dict[str, tuple[str, ...]]

    def themes_for(self, skill: str, subskill: str | None, phase: str | None = None) -> tuple:
        """Themes that train this skill; for unexplained mistakes, the game phase's theme."""
        if skill == UNCLASSIFIED:
            return self.phases.get(phase or "", ())
        return self.skills.get((skill, subskill), ())

    @property
    def all_themes(self) -> frozenset[str]:
        return frozenset(t for ts in [*self.skills.values(), *self.phases.values()] for t in ts)


def load_theme_map(path: Path = DEFAULT_PATH) -> ThemeMap:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    taxonomy = get_taxonomy()
    skills: dict[tuple[str, str | None], tuple[str, ...]] = {}
    for skill, subs in raw["skills"].items():
        for sub, themes in subs.items():
            taxonomy.require_valid(skill, sub)  # a typo in the mapping must fail loudly
            unknown = set(themes) - LICHESS_THEMES
            if unknown:
                raise ValueError(f"Unknown Lichess puzzle themes for {skill}.{sub}: {unknown}")
            skills[(skill, sub)] = tuple(themes)
    phases = {phase: tuple(themes) for phase, themes in raw["phase_themes"].items()}
    for themes in phases.values():
        if set(themes) - LICHESS_THEMES:
            raise ValueError(f"Unknown Lichess puzzle themes in phase_themes: {themes}")
    return ThemeMap(version=raw["version"], skills=skills, phases=phases)


@lru_cache
def get_theme_map() -> ThemeMap:
    local = Path("config/puzzle_themes.yaml")  # /app/config in Docker
    return load_theme_map(local if local.is_file() else DEFAULT_PATH)
