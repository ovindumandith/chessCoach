"""PGN import orchestration: validate -> store -> parse -> map identity -> dedupe -> persist."""

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.core.access import require_own_student_record
from chesscoach.core.audit import record_audit
from chesscoach.core.errors import NotFoundError, PayloadTooLargeError, ValidationFailedError
from chesscoach.db.enums import Color, ImportStatus, MappingStatus
from chesscoach.db.models import Game, SourceFile, User
from chesscoach.ingestion.identity import resolve_student_color
from chesscoach.ingestion.pgn_parser import decode_pgn_bytes, parse_pgn_text
from chesscoach.ingestion.storage import LocalFileStorage

ALLOWED_EXTENSIONS = {".pgn", ".txt"}


@dataclass
class GameImportItem:
    index: int
    status: str  # imported | needs_mapping | duplicate | rejected
    game_id: str | None = None
    white: str | None = None
    black: str | None = None
    student_color: str | None = None
    mapping_status: str | None = None
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    source_file_id: str
    sha256: str
    file_previously_uploaded: bool
    encoding: str
    total_records: int = 0
    imported: int = 0
    needs_mapping: int = 0
    duplicates: int = 0
    rejected: int = 0
    file_warnings: list[str] = field(default_factory=list)
    games: list[GameImportItem] = field(default_factory=list)


def import_pgn(
    db: Session,
    storage: LocalFileStorage,
    user: User,
    student_id: uuid.UUID,
    *,
    filename: str,
    data: bytes,
    max_bytes: int,
) -> ImportReport:
    # Students add their own games; coaches only monitor (admins may import for support).
    student = require_own_student_record(db, user, student_id, allow_admin=True)

    safe_name = PurePath(filename or "upload.pgn").name[:255]
    if PurePath(safe_name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValidationFailedError("Only .pgn (or .txt) files are accepted")
    if len(data) > max_bytes:
        raise PayloadTooLargeError(f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit")
    if not data.strip():
        raise ValidationFailedError("File is empty")

    try:
        text, encoding, file_warnings = decode_pgn_bytes(data)
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc

    parsed = parse_pgn_text(text)
    if not parsed.games and not parsed.rejected:
        raise ValidationFailedError("No PGN games found in file")

    sha256 = hashlib.sha256(data).hexdigest()
    source = db.scalar(select(SourceFile).where(SourceFile.sha256 == sha256))
    # Only this student's own imports count: whether *anyone* uploaded the file before must not
    # leak across students now that students upload too.
    previously_uploaded = source is not None and (
        db.scalar(
            select(Game.id)
            .where(Game.student_id == student.id, Game.source_file_id == source.id)
            .limit(1)
        )
        is not None
    )
    if source is None:
        storage_key = storage.save(sha256, data)
        source = SourceFile(
            original_filename=safe_name,
            sha256=sha256,
            storage_key=storage_key,
            file_size=len(data),
            encoding=encoding,
            uploaded_by=user.id,
            warnings=file_warnings,
        )
        db.add(source)
        db.flush()

    report = ImportReport(
        source_file_id=str(source.id),
        sha256=sha256,
        file_previously_uploaded=previously_uploaded,
        encoding=encoding,
        total_records=len(parsed.games) + len(parsed.rejected),
        file_warnings=file_warnings,
    )

    aliases = [a.alias_normalized for a in student.aliases]
    existing_hashes = set(
        db.scalars(select(Game.game_hash).where(Game.student_id == student.id)).all()
    )

    for pg in parsed.games:
        if pg.game_hash in existing_hashes:
            report.duplicates += 1
            report.games.append(
                GameImportItem(
                    index=pg.index,
                    status="duplicate",
                    white=pg.white,
                    black=pg.black,
                    reason="Game already imported for this student",
                )
            )
            continue

        mapping_status, color = resolve_student_color(pg.white, pg.black, aliases)
        game = Game(
            source_file_id=source.id,
            game_index=pg.index,
            game_hash=pg.game_hash,
            white_name=pg.white,
            black_name=pg.black,
            student_id=student.id,
            student_color=color,
            mapping_status=mapping_status,
            result=pg.result,
            played_at=pg.played_at,
            time_control=pg.time_control,
            opening_eco=pg.eco,
            ply_count=pg.ply_count,
            has_clock=pg.has_clock,
            pgn_headers=pg.headers,
            raw_pgn=pg.raw_pgn,
            import_warnings=pg.warnings,
            imported_by=user.id,
        )
        db.add(game)
        db.flush()
        existing_hashes.add(pg.game_hash)

        mapped = mapping_status == MappingStatus.MAPPED
        if mapped:
            report.imported += 1
        else:
            report.needs_mapping += 1
        report.games.append(
            GameImportItem(
                index=pg.index,
                status="imported" if mapped else "needs_mapping",
                game_id=str(game.id),
                white=pg.white,
                black=pg.black,
                student_color=color.value if color else None,
                mapping_status=mapping_status.value,
                reason=None if mapped else _mapping_reason(mapping_status),
                warnings=pg.warnings,
            )
        )

    for rj in parsed.rejected:
        report.rejected += 1
        report.games.append(
            GameImportItem(
                index=rj.index, status="rejected", white=rj.white, black=rj.black, reason=rj.reason
            )
        )
    report.games.sort(key=lambda g: g.index)

    if report.rejected and not (report.imported or report.needs_mapping or report.duplicates):
        source.import_status = ImportStatus.FAILED
    elif report.rejected or report.needs_mapping:
        source.import_status = ImportStatus.COMPLETED_WITH_ERRORS
    else:
        source.import_status = ImportStatus.COMPLETED
    source.import_report = asdict(report)

    record_audit(
        db,
        actor_user_id=user.id,
        action="games.import",
        entity_type="source_file",
        entity_id=source.id,
        details={
            "student_id": str(student.id),
            "imported": report.imported,
            "needs_mapping": report.needs_mapping,
            "duplicates": report.duplicates,
            "rejected": report.rejected,
        },
    )
    db.commit()
    return report


def confirm_game_mapping(db: Session, user: User, game_id: uuid.UUID, student_color: Color) -> Game:
    """The student confirms which color they played in an unmatched/ambiguous game (they know
    which side they were on). Audited."""
    game = db.get(Game, game_id)
    if game is None:
        raise NotFoundError("Game not found")
    require_own_student_record(db, user, game.student_id, allow_admin=True)
    previous = game.mapping_status
    game.student_color = student_color
    game.mapping_status = MappingStatus.CONFIRMED
    record_audit(
        db,
        actor_user_id=user.id,
        action="game.mapping_confirm",
        entity_type="game",
        entity_id=game.id,
        details={"previous_status": previous.value, "student_color": student_color.value},
    )
    db.commit()
    return game


def _mapping_reason(status: MappingStatus) -> str:
    if status == MappingStatus.AMBIGUOUS:
        return "Both players match this student's PGN names; confirm which side the student played"
    return (
        "Neither player matches this student's PGN names; confirm the side in the games list "
        "(the coach can add the name as an alias)"
    )
