"""Stockfish integration through python-chess UCI.

One long-lived engine process per worker; never one per move.
"""

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

import chess
import chess.engine


@dataclass(frozen=True)
class EngineConfig:
    path: str
    depth: int
    threads: int = 1
    hash_mb: int = 256
    multipv: int = 2

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("path")  # machine-specific; the engine version + checksum identify it
        return data


@dataclass
class EngineLine:
    score: chess.engine.PovScore
    pv: list[chess.Move]
    depth: int | None


@dataclass
class EngineIdentity:
    name: str
    version: str | None
    checksum: str | None
    options: dict = field(default_factory=dict)


class PositionAnalyzer(Protocol):
    """What the game analyzer needs from an engine. Lets tests use a fake."""

    identity: EngineIdentity

    def analyse(
        self, board: chess.Board, *, depth: int, multipv: int, game_key: object
    ) -> list[EngineLine]: ...


def file_sha256(path: str | Path) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class StockfishAnalyzer:
    """Context-managed Stockfish process."""

    def __init__(self, config: EngineConfig):
        self.config = config
        self._engine: chess.engine.SimpleEngine | None = None
        self.identity = EngineIdentity(name="unknown", version=None, checksum=None)

    def __enter__(self) -> "StockfishAnalyzer":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        if not Path(self.config.path).is_file():
            raise FileNotFoundError(f"Stockfish binary not found at {self.config.path!r}")
        self._engine = chess.engine.SimpleEngine.popen_uci(self.config.path)
        self._engine.configure({"Threads": self.config.threads, "Hash": self.config.hash_mb})
        full_name = self._engine.id.get("name", "unknown")
        name, _, version = full_name.partition(" ")
        self.identity = EngineIdentity(
            name=name or full_name,
            version=version or None,
            checksum=file_sha256(self.config.path),
            options={"Threads": self.config.threads, "Hash": self.config.hash_mb},
        )

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except chess.engine.EngineTerminatedError:
                pass
            self._engine = None

    def analyse(
        self, board: chess.Board, *, depth: int, multipv: int, game_key: object
    ) -> list[EngineLine]:
        if self._engine is None:
            raise RuntimeError("Engine is not open")
        # `game=` makes python-chess send `ucinewgame` when the game changes, so hash
        # contents from one game do not leak into another (reproducibility).
        infos = self._engine.analyse(
            board, chess.engine.Limit(depth=depth), multipv=multipv, game=game_key
        )
        return [
            EngineLine(score=info["score"], pv=list(info.get("pv", [])), depth=info.get("depth"))
            for info in infos
            if "score" in info
        ]
