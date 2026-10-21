"""Load Lichess puzzles into the puzzle library.

    python -m chesscoach.puzzles.load --hf [--cache-dir data/puzzles] [--files 3]
    python -m chesscoach.puzzles.load path/to/train-00000-of-00003.parquet [more.parquet ...]
    python -m chesscoach.puzzles.load lichess_db_puzzle.csv

--hf downloads the Parquet files of the Hugging Face dataset Lichess/chess-puzzles (CC0,
about 885 MB in three files) at its current revision, which is recorded on every puzzle.
Downloads are cached, so a re-run does not download again. Re-running is safe: puzzles
already in the library are skipped.
"""

import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path

import httpx

from chesscoach.db.session import get_sessionmaker
from chesscoach.puzzles.importer import ImportFilter, import_puzzles, iter_file

log = logging.getLogger("chesscoach.puzzles")

HF_DATASET = "Lichess/chess-puzzles"
HF = "https://huggingface.co"


def hf_download(cache_dir: Path, max_files: int | None = None) -> tuple[list[Path], str]:
    """Download the dataset's Parquet files at its current revision. Returns (paths, source)."""
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        sha = client.get(f"{HF}/api/datasets/{HF_DATASET}").raise_for_status().json()["sha"]
        listing = client.get(f"{HF}/api/datasets/{HF_DATASET}/tree/{sha}/data").raise_for_status()
        files = sorted(
            (f for f in listing.json() if f["path"].endswith(".parquet")), key=lambda f: f["path"]
        )[:max_files]
        target = cache_dir / sha[:12]
        target.mkdir(parents=True, exist_ok=True)
        paths = []
        for f in files:
            path = target / Path(f["path"]).name
            if not (path.is_file() and path.stat().st_size == f["size"]):
                log.info("downloading %s (%.0f MB)", f["path"], f["size"] / 1e6)
                part = path.with_suffix(".part")
                url = f"{HF}/datasets/{HF_DATASET}/resolve/{sha}/{f['path']}"
                with client.stream("GET", url, timeout=600) as resp, part.open("wb") as out:
                    resp.raise_for_status()
                    for chunk in resp.iter_bytes(1 << 20):
                        out.write(chunk)
                if part.stat().st_size != f["size"]:
                    raise RuntimeError(f"Incomplete download of {f['path']}")
                part.replace(path)
            paths.append(path)
    return paths, f"hf:{HF_DATASET}@{sha[:12]}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help=".parquet or .csv files")
    parser.add_argument("--hf", action="store_true", help=f"download {HF_DATASET}")
    parser.add_argument("--cache-dir", type=Path, default=Path("data/puzzles"))
    parser.add_argument("--files-limit", type=int, default=None, help="only the first N HF files")
    parser.add_argument("--source", help="recorded source label for local files")
    defaults = ImportFilter()
    parser.add_argument("--max-rd", type=int, default=defaults.max_rd)
    parser.add_argument("--min-plays", type=int, default=defaults.min_plays)
    parser.add_argument("--min-popularity", type=int, default=defaults.min_popularity)
    parser.add_argument("--per-band", type=int, default=defaults.per_band)
    parser.add_argument("--band-width", type=int, default=defaults.band_width)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.hf:
        paths, source = hf_download(args.cache_dir, args.files_limit)
    elif args.files:
        paths, source = args.files, args.source or "file:" + ",".join(p.name for p in args.files)
    else:
        parser.error("give puzzle files or --hf")
    filt = ImportFilter(
        max_rd=args.max_rd,
        min_plays=args.min_plays,
        min_popularity=args.min_popularity,
        per_band=args.per_band,
        band_width=args.band_width,
    )
    with get_sessionmaker()() as db:
        for path in paths:
            report = import_puzzles(db, iter_file(path), source=source, filt=filt)
            print(json.dumps({"file": path.name, **asdict(report)}, indent=2))


if __name__ == "__main__":
    main()
