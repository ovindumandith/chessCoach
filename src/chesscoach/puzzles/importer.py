"""Import puzzles from the Lichess puzzle database into the puzzle library.

Reads the Hugging Face Parquet files (Lichess/chess-puzzles) or the Lichess CSV export.
Keeps a balanced, useful slice rather than all ~6M puzzles:

- reliable ratings only (RatingDeviation <= max_rd), played enough, not disliked
- at least one theme that some skill is trained with (config/puzzle_themes.yaml)
- at most `per_band` puzzles per (theme, rating band), so every theme has puzzles at every
  level
- the whole move line must be legal (python-chess), start with the opponent's move and end
  with the player's (an even number of moves)

Idempotent: puzzles already in the library are skipped, and caps count what is stored.
"""

import csv
import logging
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

import chess
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from chesscoach.db.models import Puzzle, PuzzleTheme
from chesscoach.db.types import new_uuid, utcnow
from chesscoach.puzzles.themes import get_theme_map

log = logging.getLogger("chesscoach.puzzles")

COLUMNS = [
    "PuzzleId",
    "GameId",
    "FEN",
    "Moves",
    "Rating",
    "RatingDeviation",
    "Popularity",
    "NbPlays",
    "Themes",
    "OpeningTags",
]


@dataclass
class ImportFilter:
    max_rd: int = 90
    min_plays: int = 100
    min_popularity: int = 50
    per_band: int = 150
    band_width: int = 100


@dataclass
class ImportReport:
    source: str
    scanned: int = 0
    imported: int = 0
    skipped_quality: int = 0  # rating deviation, plays or popularity
    skipped_no_theme: int = 0  # no theme any skill is trained with
    skipped_full: int = 0  # every matching (theme, band) already full
    skipped_invalid: int = 0  # illegal or malformed move line
    skipped_existing: int = 0
    library_size: int = 0
    filters: dict = field(default_factory=dict)


def iter_parquet(path: Path, batch_size: int = 50_000) -> Iterator[dict]:
    import pyarrow.parquet as pq  # imported lazily: only the importer needs pyarrow

    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size, columns=COLUMNS):
        yield from batch.to_pylist()


def iter_csv(path: Path) -> Iterator[dict]:
    """The Lichess CSV export: Themes and OpeningTags are space separated, GameUrl a URL."""
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            url = row.get("GameUrl") or ""
            yield {
                **row,
                "GameId": url.removeprefix("https://lichess.org/") or None,
                "Themes": (row.get("Themes") or "").split(),
                "OpeningTags": (row.get("OpeningTags") or "").split(),
            }


def iter_file(path: Path) -> Iterator[dict]:
    if path.suffix == ".parquet":
        return iter_parquet(path)
    if path.suffix == ".csv":
        return iter_csv(path)
    raise ValueError(f"Unsupported puzzle file (want .parquet or .csv): {path.name}")


def valid_line(fen: str, moves: list[str]) -> bool:
    """Opponent move first, player move last, every move legal."""
    if len(moves) < 2 or len(moves) % 2:
        return False
    try:
        board = chess.Board(fen)
        for uci in moves:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                return False
            board.push(move)
    except ValueError:
        return False
    return True


def import_puzzles(
    db: Session,
    rows: Iterable[dict],
    *,
    source: str,
    filt: ImportFilter | None = None,
    commit_every: int = 2000,
) -> ImportReport:
    filt = filt or ImportFilter()
    wanted = get_theme_map().all_themes
    report = ImportReport(source=source, filters=asdict(filt))

    known = set(db.scalars(select(Puzzle.lichess_id)))
    bands: Counter = Counter(
        (theme, rating // filt.band_width)
        for theme, rating in db.execute(
            select(PuzzleTheme.theme, PuzzleTheme.rating).where(PuzzleTheme.theme.in_(wanted))
        )
    )
    puzzles: list[dict] = []
    themes: list[dict] = []

    def flush() -> None:
        if puzzles:
            db.execute(insert(Puzzle), puzzles)
            db.execute(insert(PuzzleTheme), themes)
            db.commit()
            puzzles.clear()
            themes.clear()

    for row in rows:
        report.scanned += 1
        rd, plays, popularity = row["RatingDeviation"], row["NbPlays"], row["Popularity"]
        if (
            int(rd) > filt.max_rd
            or int(plays) < filt.min_plays
            or int(popularity) < filt.min_popularity
        ):
            report.skipped_quality += 1
            continue
        puzzle_themes = list(row["Themes"] or [])
        matching = [t for t in puzzle_themes if t in wanted]
        if not matching:
            report.skipped_no_theme += 1
            continue
        rating = int(row["Rating"])
        band = rating // filt.band_width
        if all(bands[(t, band)] >= filt.per_band for t in matching):
            report.skipped_full += 1
            continue
        if row["PuzzleId"] in known:
            report.skipped_existing += 1
            continue
        moves = row["Moves"].split()
        if not valid_line(row["FEN"], moves):
            report.skipped_invalid += 1
            continue

        pid = new_uuid()
        puzzles.append(
            {
                "id": pid,
                "lichess_id": row["PuzzleId"],
                "fen": row["FEN"],
                "moves": " ".join(moves),
                "rating": rating,
                "rating_deviation": int(rd),
                "popularity": int(popularity),
                "nb_plays": int(plays),
                "themes": puzzle_themes,
                "opening_tags": list(row.get("OpeningTags") or []),
                "game_ref": row.get("GameId"),
                "source": source,
                "created_at": utcnow(),
            }
        )
        themes.extend({"puzzle_id": pid, "theme": t, "rating": rating} for t in puzzle_themes)
        for t in matching:
            bands[(t, band)] += 1
        known.add(row["PuzzleId"])
        report.imported += 1
        if len(puzzles) >= commit_every:
            flush()
            log.info("imported %d puzzles (scanned %d)", report.imported, report.scanned)
    flush()
    report.library_size = len(known)
    return report
