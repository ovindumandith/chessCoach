"""Pure PGN parsing: bytes -> validated game records. No database, engine, or LLM access."""

import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import date

import chess
import chess.pgn

from chesscoach.db.enums import GameResult

HASH_HEADERS = ("Event", "Site", "Date", "Round", "White", "Black", "Result")
_UNKNOWN_HEADER_VALUES = {"", "?", "??", "-"}


@dataclass
class ParsedGame:
    index: int
    headers: dict[str, str]
    white: str
    black: str
    result: GameResult
    played_at: date | None
    time_control: str | None
    eco: str | None
    uci_moves: list[str]
    has_clock: bool
    raw_pgn: str
    game_hash: str
    warnings: list[str] = field(default_factory=list)

    @property
    def ply_count(self) -> int:
        return len(self.uci_moves)


@dataclass
class RejectedGame:
    index: int
    reason: str
    white: str | None = None
    black: str | None = None


@dataclass
class ParseResult:
    games: list[ParsedGame]
    rejected: list[RejectedGame]


def decode_pgn_bytes(data: bytes) -> tuple[str, str, list[str]]:
    """Decode an uploaded PGN. Returns (text, encoding, warnings)."""
    if b"\x00" in data:
        raise ValueError("File contains NUL bytes; it does not look like a PGN text file")
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding), "utf-8", []
        except UnicodeDecodeError:
            continue
    # latin-1 never fails; flag it so a coach can check player names.
    return data.decode("latin-1"), "latin-1", ["File is not valid UTF-8; decoded as Latin-1"]


def normalize_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def compute_game_hash(headers: dict[str, str], uci_moves: list[str]) -> str:
    key = {h: normalize_name(headers.get(h, "")) for h in HASH_HEADERS}
    payload = json.dumps({"headers": key, "moves": uci_moves}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def parse_pgn_date(value: str | None) -> date | None:
    """Parse a PGN `YYYY.MM.DD` date. Partial or unknown dates return None."""
    if not value or "?" in value:
        return None
    try:
        y, m, d = (int(p) for p in value.split("."))
        return date(y, m, d)
    except ValueError:
        return None


def _clean(value: str | None) -> str | None:
    if value is None or value.strip() in _UNKNOWN_HEADER_VALUES:
        return None
    return value.strip()


def parse_pgn_text(text: str) -> ParseResult:
    games: list[ParsedGame] = []
    rejected: list[RejectedGame] = []
    stream = io.StringIO(text)
    index = 0

    while True:
        start = stream.tell()
        try:
            game = chess.pgn.read_game(stream)
        except Exception as exc:  # defensive: python-chess is lenient, but never crash an import
            rejected.append(RejectedGame(index=index, reason=f"Unreadable PGN record: {exc}"))
            break
        if game is None:
            break
        end = stream.tell()
        raw = text[start:end].strip()
        headers = dict(game.headers)
        white = headers.get("White", "").strip()
        black = headers.get("Black", "").strip()

        reason = _rejection_reason(game, white, black)
        if reason:
            rejected.append(RejectedGame(index=index, reason=reason, white=white, black=black))
            index += 1
            continue

        warnings: list[str] = []
        uci_moves: list[str] = []
        has_clock = False
        for node in game.mainline():
            uci_moves.append(node.move.uci())
            if node.clock() is not None:
                has_clock = True

        result_header = headers.get("Result", "*")
        try:
            result = GameResult(result_header)
        except ValueError:
            result = GameResult.UNKNOWN
            warnings.append(f"Unrecognized result {result_header!r}; stored as '*'")

        played_at = parse_pgn_date(headers.get("Date") or headers.get("UTCDate"))
        if played_at is None:
            warnings.append("Missing or partial date")

        games.append(
            ParsedGame(
                index=index,
                headers=headers,
                white=white,
                black=black,
                result=result,
                played_at=played_at,
                time_control=_clean(headers.get("TimeControl")),
                eco=_clean(headers.get("ECO")),
                uci_moves=uci_moves,
                has_clock=has_clock,
                raw_pgn=raw,
                game_hash=compute_game_hash(headers, uci_moves),
                warnings=warnings,
            )
        )
        index += 1

    return ParseResult(games=games, rejected=rejected)


def _rejection_reason(game: chess.pgn.Game, white: str, black: str) -> str | None:
    if game.errors:
        return "; ".join(str(e) for e in game.errors)[:500]
    if "FEN" in game.headers or game.headers.get("SetUp") == "1":
        # Positions not starting from the initial array are valid PGN, but student-game
        # analysis assumes full games. Revisit if coaches import composed positions.
        return "Games from a custom starting position (FEN/SetUp) are not supported yet"
    if game.headers.get("Variant", "Standard").lower() not in {"standard", "chess"}:
        return f"Unsupported variant: {game.headers.get('Variant')}"
    if game.next() is None:
        return "Game contains no moves"
    if _clean(white) is None or _clean(black) is None:
        return "Missing White or Black player name"
    return None
