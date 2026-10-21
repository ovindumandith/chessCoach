"""Puzzle sets for a student's mistakes, solving them move by move, and puzzle ratings.

A set holds (usually) four puzzles of the mistake's kind, each rated higher than the one
before, starting below the student's puzzle rating for that skill (see selection.py).
Solving follows Lichess: the opponent's first move is played for the student; every
player move must match the solution, except that any move that mates also solves; the
first wrong move decides the puzzle as failed for the rating, but the student may keep
trying. Each decided puzzle updates the student's rating for the skill, so the next set
is harder after successes and easier after failures.
"""

import uuid

import chess
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chesscoach.classification.classifier import CLASSIFIER_VERSION
from chesscoach.classification.taxonomy import UNCLASSIFIED
from chesscoach.core.access import require_own_student_record, require_student_access
from chesscoach.core.audit import record_audit
from chesscoach.core.errors import ConflictError, NotFoundError, ValidationFailedError
from chesscoach.db.enums import PuzzleResult, PuzzleStatus, ReviewStatus
from chesscoach.db.models import (
    Game,
    MoveAnalysis,
    Puzzle,
    PuzzleAssignment,
    PuzzleTheme,
    Student,
    StudentPuzzleRating,
    User,
    WeaknessObservation,
)
from chesscoach.db.types import utcnow
from chesscoach.puzzles import rating as glicko
from chesscoach.puzzles.selection import SELECTION, Candidate, pick, targets
from chesscoach.puzzles.themes import get_theme_map

# --------------------------------------------------------------------------- choosing puzzles


def _mistake_skill(db: Session, game: Game, ply: int) -> tuple[str, str | None, str | None]:
    """(skill, subskill, phase) of the student's mistake on this move: the most severe
    verified finding, or `unclassified` when no cause was verified."""
    rows = db.execute(
        select(WeaknessObservation, MoveAnalysis.phase)
        .join(MoveAnalysis, MoveAnalysis.id == WeaknessObservation.move_analysis_id)
        .where(
            WeaknessObservation.game_id == game.id,
            MoveAnalysis.ply == ply,
            WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
            WeaknessObservation.review_status != ReviewStatus.REJECTED,
        )
    ).all()
    if not rows:
        raise NotFoundError("No mistake was found on this move")
    phase = rows[0][1].value
    specific = [o for o, _ in rows if o.skill_code != UNCLASSIFIED]
    best = max(specific or [o for o, _ in rows], key=lambda o: o.severity or 0.0)
    return best.skill_code, best.subskill_code, phase


def _rating_row(db: Session, student: Student, skill: str, sub: str | None) -> StudentPuzzleRating:
    row = db.scalar(
        select(StudentPuzzleRating).where(
            StudentPuzzleRating.student_id == student.id,
            StudentPuzzleRating.skill_code == skill,
            StudentPuzzleRating.subskill_code.is_(None)
            if sub is None
            else StudentPuzzleRating.subskill_code == sub,
        )
    )
    if row is None:
        row = StudentPuzzleRating(
            student_id=student.id,
            skill_code=skill,
            subskill_code=sub,
            rating=float(student.rating_estimate or SELECTION["default_rating"]),
            puzzles_decided=0,
        )
        db.add(row)
        db.flush()
    return row


def _candidates(
    db: Session, student_id: uuid.UUID, themes: tuple, lo: int, hi: int, target: int
) -> list[Candidate]:
    seen = select(PuzzleAssignment.puzzle_id).where(PuzzleAssignment.student_id == student_id)
    rows = db.execute(
        select(
            PuzzleTheme.puzzle_id,
            PuzzleTheme.theme,
            PuzzleTheme.rating,
            Puzzle.rating_deviation,
            Puzzle.popularity,
        )
        .join(Puzzle, Puzzle.id == PuzzleTheme.puzzle_id)
        .where(
            PuzzleTheme.theme.in_(themes),
            PuzzleTheme.rating.between(lo, hi),
            Puzzle.rating_deviation <= SELECTION["max_rd"],
            PuzzleTheme.puzzle_id.not_in(seen),
        )
        .order_by(func.abs(PuzzleTheme.rating - target))
        .limit(200)
    ).all()
    return [Candidate(*r) for r in rows]


def _create_set(
    db: Session,
    user: User,
    student: Student,
    skill: str,
    sub: str | None,
    themes: tuple,
    *,
    game: Game | None = None,
    ply: int | None = None,
) -> uuid.UUID:
    if not themes:
        raise ConflictError(
            "Tactical puzzles cannot train this kind of mistake yet (for example positional "
            "play); there is no matching Lichess puzzle theme."
        )
    if db.scalar(select(func.count()).select_from(Puzzle)) == 0:
        raise ConflictError(
            "The puzzle library is empty. An administrator loads it with "
            "`python -m chesscoach.puzzles.load --hf`."
        )
    current = _rating_row(db, student, skill, sub)
    set_id = uuid.uuid4()
    chosen: list[tuple[int, Candidate]] = []
    above: int | None = None
    for target in targets(current.rating):
        found = None
        window = SELECTION["window"]
        for _ in range(SELECTION["max_widen"] + 1):
            lo = max(target - window, (above or 0) + 1)
            found = pick(
                _candidates(db, student.id, themes, lo, target + window, target), target, above
            )
            if found or target - window <= (above or 0):
                break
            window *= 2
        if found and all(found.puzzle_id != c.puzzle_id for _, c in chosen):
            chosen.append((target, found))
            above = found.rating
    if not chosen:
        raise ConflictError("No new puzzles of this kind are left at your level.")
    for i, (target, c) in enumerate(chosen, start=1):
        db.add(
            PuzzleAssignment(
                student_id=student.id,
                puzzle_id=c.puzzle_id,
                set_id=set_id,
                position=i,
                skill_code=skill,
                subskill_code=sub,
                theme=c.theme,
                source_game_id=game.id if game else None,
                source_ply=ply,
                target_rating=target,
                student_rating_before=current.rating,
                selection_version=f"{SELECTION['version']}/{get_theme_map().version}",
            )
        )
    record_audit(
        db,
        actor_user_id=user.id,
        action="puzzles.set_create",
        entity_type="student",
        entity_id=student.id,
        details={"set_id": str(set_id), "skill": skill, "subskill": sub, "count": len(chosen)},
    )
    db.commit()
    return set_id


def set_for_mistake(db: Session, user: User, game_id: uuid.UUID, ply: int) -> dict:
    """Puzzles for the student's mistake on this move. Reuses an unfinished set."""
    game = db.get(Game, game_id)
    if game is None:
        raise NotFoundError("Game not found")
    student = require_own_student_record(db, user, game.student_id)
    open_set = db.scalar(
        select(PuzzleAssignment.set_id).where(
            PuzzleAssignment.student_id == student.id,
            PuzzleAssignment.source_game_id == game.id,
            PuzzleAssignment.source_ply == ply,
            PuzzleAssignment.status == PuzzleStatus.OPEN,
        )
    )
    if open_set is None:
        skill, sub, phase = _mistake_skill(db, game, ply)
        themes = get_theme_map().themes_for(skill, sub, phase)
        open_set = _create_set(db, user, student, skill, sub, themes, game=game, ply=ply)
    return get_set(db, user, open_set)


def set_for_skill(
    db: Session, user: User, student_id: uuid.UUID, skill: str, sub: str | None
) -> dict:
    """Puzzles for a skill, for example the one the AI recommendation is about."""
    student = require_own_student_record(db, user, student_id)
    themes = get_theme_map().themes_for(skill, sub)
    return get_set(db, user, _create_set(db, user, student, skill, sub, themes))


# --------------------------------------------------------------------------- views


def _board(p: Puzzle, plies: int) -> chess.Board:
    board = chess.Board(p.fen)
    for uci in p.moves.split()[:plies]:
        board.push_uci(uci)
    return board


def assignment_view(a: PuzzleAssignment) -> dict:
    p = a.puzzle
    moves = p.moves.split()
    board = _board(p, a.progress)
    done = a.status != PuzzleStatus.OPEN
    student_side = "white" if chess.Board(p.fen).turn == chess.BLACK else "black"
    return {
        "id": str(a.id),
        "set_id": str(a.set_id),
        "position": a.position,
        "skill_code": a.skill_code,
        "subskill_code": a.subskill_code,
        "theme": a.theme,
        "rating": p.rating,
        "rating_deviation": p.rating_deviation,
        "themes": p.themes,
        "fen": board.fen(),
        "last_move": moves[a.progress - 1],
        "student_side": student_side,
        "status": a.status.value,
        "result": a.result.value if a.result else None,
        "wrong_moves": a.wrong_moves,
        "moves_left": (len(moves) - a.progress + 1) // 2,
        # Only once finished: the full line from the student's first move, and the source.
        "solution": moves[1:] if done else None,
        "start_fen": _board(p, 1).fen() if done else None,
        "lichess_url": f"https://lichess.org/training/{p.lichess_id}" if done else None,
    }


def get_set(db: Session, user: User, set_id: uuid.UUID) -> dict:
    rows = list(
        db.scalars(
            select(PuzzleAssignment)
            .where(PuzzleAssignment.set_id == set_id)
            .order_by(PuzzleAssignment.position)
        )
    )
    if not rows:
        raise NotFoundError("Puzzle set not found")
    student_id = rows[0].student_id
    require_student_access(db, user, student_id)
    first = rows[0]
    source = None
    if first.source_game_id:
        game = db.get(Game, first.source_game_id)
        move = db.scalar(
            select(MoveAnalysis.san_move)
            .join(WeaknessObservation, WeaknessObservation.move_analysis_id == MoveAnalysis.id)
            .where(WeaknessObservation.game_id == game.id, MoveAnalysis.ply == first.source_ply)
            .limit(1)
        )
        white = game.student_color is not None and game.student_color.value == "white"
        source = {
            "game_id": str(game.id),
            "ply": first.source_ply,
            "move_number": (first.source_ply + 1) // 2,
            "san": move,
            "opponent": game.black_name if white else game.white_name,
            "played_at": game.played_at.isoformat() if game.played_at else None,
        }
    current = db.scalar(
        select(StudentPuzzleRating.rating).where(
            StudentPuzzleRating.student_id == student_id,
            StudentPuzzleRating.skill_code == first.skill_code,
            StudentPuzzleRating.subskill_code.is_(None)
            if first.subskill_code is None
            else StudentPuzzleRating.subskill_code == first.subskill_code,
        )
    )
    return {
        "set_id": str(set_id),
        "student_id": str(student_id),
        "skill_code": first.skill_code,
        "subskill_code": first.subskill_code,
        "source": source,
        "created_at": first.created_at.isoformat(),
        "rating_before": round(first.student_rating_before),
        "rating_now": round(current) if current is not None else None,
        "solved": sum(1 for a in rows if a.result == PuzzleResult.SOLVED),
        "puzzles": [assignment_view(a) for a in rows],
    }


def list_sets(db: Session, user: User, student_id: uuid.UUID) -> dict:
    require_student_access(db, user, student_id)
    set_ids = db.scalars(
        select(PuzzleAssignment.set_id)
        .where(PuzzleAssignment.student_id == student_id)
        .group_by(PuzzleAssignment.set_id)
        .order_by(func.max(PuzzleAssignment.created_at).desc())
    ).all()
    library = db.scalar(select(func.count()).select_from(Puzzle))
    return {"library_size": library, "sets": [get_set(db, user, s) for s in set_ids]}


# --------------------------------------------------------------------------- solving


def _own_assignment(db: Session, user: User, assignment_id: uuid.UUID) -> PuzzleAssignment:
    a = db.get(PuzzleAssignment, assignment_id)
    if a is None:
        raise NotFoundError("Puzzle not found")
    require_own_student_record(db, user, a.student_id)
    return a


def _decide(db: Session, a: PuzzleAssignment, solved: bool) -> None:
    """Record the first decision and update the student's rating for the skill (once)."""
    if a.result is not None:
        return
    a.result = PuzzleResult.SOLVED if solved else PuzzleResult.FAILED
    student = db.get(Student, a.student_id)
    row = _rating_row(db, student, a.skill_code, a.subskill_code)
    k = (
        SELECTION["k_provisional"]
        if row.puzzles_decided < SELECTION["provisional_puzzles"]
        else SELECTION["k"]
    )
    row.rating = glicko.updated(row.rating, a.puzzle.rating, a.puzzle.rating_deviation, solved, k=k)
    row.puzzles_decided += 1
    row.updated_at = utcnow()


def play_move(db: Session, user: User, assignment_id: uuid.UUID, uci: str) -> dict:
    a = _own_assignment(db, user, assignment_id)
    if a.status != PuzzleStatus.OPEN:
        raise ConflictError("This puzzle is finished")
    moves = a.puzzle.moves.split()
    board = _board(a.puzzle, a.progress)
    try:
        move = chess.Move.from_uci(uci)
    except ValueError as exc:
        raise ValidationFailedError("Not a move in UCI notation") from exc
    if move not in board.legal_moves:
        raise ValidationFailedError("Illegal move")  # never counted, like exercises

    expected = moves[a.progress]
    board.push(move)
    if uci != expected and not board.is_checkmate():
        a.wrong_moves += 1
        _decide(db, a, solved=False)
        db.commit()
        return {"correct": False, "reply": None, "puzzle": assignment_view(a)}

    a.progress += 1
    reply = None
    if a.progress >= len(moves) or board.is_checkmate():
        a.status = PuzzleStatus.COMPLETED
        a.finished_at = utcnow()
        _decide(db, a, solved=True)
    else:
        reply = moves[a.progress]  # the opponent's answer from the solution
        a.progress += 1
    db.commit()
    return {"correct": True, "reply": reply, "puzzle": assignment_view(a)}


def reveal(db: Session, user: User, assignment_id: uuid.UUID) -> dict:
    a = _own_assignment(db, user, assignment_id)
    if a.status == PuzzleStatus.OPEN:
        _decide(db, a, solved=False)
        a.status = PuzzleStatus.REVEALED
        a.finished_at = utcnow()
        db.commit()
    return assignment_view(a)
