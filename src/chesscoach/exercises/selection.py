"""Choose exercise positions from a student's analyzed games. Pure functions over stored
analysis rows; no database access, no engine calls.

A position qualifies only if its solution is unambiguous by the stored engine evidence:
a forced mate, or a best move clearly ahead of the second-best line. Otherwise a sound
alternative would be marked "wrong", the classic bad-puzzle failure.
"""

from dataclasses import dataclass, field

import chess

from chesscoach.analysis.scores import Evaluation, win_probability
from chesscoach.classification.classifier import THRESHOLDS, endgame_type
from chesscoach.classification.motifs import detect_missed

SELECTION_VERSION = "exercise-selection-v1"

UNIQUE_GAP = 0.15  # best line must beat the 2nd-best by this much win probability
MIN_LEGAL_MOVES = 3  # positions with 1-2 legal moves are not exercises
TACTICAL_SUBSKILLS = ("forks", "hanging_pieces", "mating_patterns")
NOT_EXERCISABLE = {("practical_play", "time_management")}  # not a board skill

HINTS = {
    "forks": "Look for a move that attacks two valuable targets at once.",
    "hanging_pieces": "One of your opponent's pieces can be won.",
    "mating_patterns": "There is a forced checkmate.",
    "pawn_endgames": "Count the pawn race and think about king activity.",
    "rook_endgames": "Activate your rook and king before anything else.",
    "general_endgames": "Think about king activity and passed pawns.",
    "preserving_advantage": "You are winning. Find the move that keeps it safest.",
    "finding_resources": "Only one move holds the position. Check every threat first.",
}
PIECE_NAMES = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}


@dataclass
class PositionInput:
    move_analysis_id: str
    game_id: str
    ply: int
    fen: str
    phase: str
    played_uci: str
    played_san: str
    best_uci: str | None
    eval_before: Evaluation
    eval_after_text: str
    gap: float | None
    legal_moves: int | None
    best_line_san: list[str]


@dataclass
class Candidate:
    position: PositionInput
    accepted_moves: list[str]
    difficulty: str
    hints: list[str]
    explanation: str
    details: dict = field(default_factory=dict)


def is_exercisable(skill_code: str, subskill_code: str | None) -> bool:
    return (skill_code, subskill_code) not in NOT_EXERCISABLE and skill_code != "unclassified"


def unique_solution(p: PositionInput) -> bool:
    mate = p.eval_before.mate
    if mate is not None and mate > 0:
        return True
    return p.gap is not None and p.gap >= UNIQUE_GAP


def relevant(p: PositionInput, skill_code: str, subskill_code: str | None, labelled: bool) -> bool:
    """Does this position test the skill? `labelled` = an observation names this skill here
    (covers coach-corrected and coach-only skills)."""
    if labelled:
        return True
    wp = win_probability(p.eval_before)
    if skill_code == "tactical_awareness" and subskill_code in TACTICAL_SUBSKILLS:
        return any(
            m.subskill == subskill_code
            for m in detect_missed(p.fen, p.best_uci, p.eval_before.mate)
        )
    if skill_code == "endgame_technique" and subskill_code:
        return p.phase == "endgame" and endgame_type(p.fen) == subskill_code
    if (skill_code, subskill_code) == ("winning_position_conversion", "preserving_advantage"):
        return wp >= THRESHOLDS["winning_wp"]
    if (skill_code, subskill_code) == ("defensive_skills", "finding_resources"):
        return (
            THRESHOLDS["defensive_min_wp"] <= wp < THRESHOLDS["winning_wp"]
            and p.gap is not None
            and p.gap >= THRESHOLDS["only_move_gap"]
        )
    return False


DEFENSIVE_HINT = (
    "Your opponent has a dangerous threat. Look at what they can do after "
    "each candidate move, then find the move that stops it."
)


def first_hint(p: PositionInput, subskill_code: str | None) -> str:
    """The theme hint must match the task. A tactical skill can be tested from either side:
    the solution contains the motif (attack), or the student must stop the opponent's
    motif (defence, e.g. a position where they allowed mate in the game)."""
    if subskill_code in TACTICAL_SUBSKILLS:
        in_solution = any(
            m.subskill == subskill_code
            for m in detect_missed(p.fen, p.best_uci, p.eval_before.mate)
        )
        return HINTS[subskill_code] if in_solution else DEFENSIVE_HINT
    return HINTS.get(subskill_code or "", "Check every forcing move: checks, captures, threats.")


def build_candidate(p: PositionInput, subskill_code: str | None) -> Candidate | None:
    board = chess.Board(p.fen)
    if p.best_uci is None or (p.legal_moves or board.legal_moves.count()) < MIN_LEGAL_MOVES:
        return None
    best = chess.Move.from_uci(p.best_uci)
    if best not in board.legal_moves or not unique_solution(p):
        return None

    accepted = [p.best_uci]
    mate = p.eval_before.mate
    if mate == 1:  # any mate-in-one is correct; verified by the rules, not the engine
        for move in board.legal_moves:
            board.push(move)
            if board.is_checkmate() and move.uci() not in accepted:
                accepted.append(move.uci())
            board.pop()

    piece = board.piece_type_at(best.from_square)
    hints = [
        first_hint(p, subskill_code),
        f"Use your {PIECE_NAMES[piece]}.",
        f"The {PIECE_NAMES[piece]} on {chess.square_name(best.from_square)}.",
    ]
    if mate is not None and mate > 0:
        difficulty = "easy" if mate == 1 else "medium" if mate == 2 else "hard"
    else:
        difficulty = "easy" if p.gap >= 0.4 else "medium" if p.gap >= 0.25 else "hard"

    line = " ".join(p.best_line_san[:6])
    explanation = f"The engine's line: {line}." if line else ""
    return Candidate(
        position=p,
        accepted_moves=accepted,
        difficulty=difficulty,
        hints=hints,
        explanation=explanation,
        details={
            "selection_version": SELECTION_VERSION,
            "unique_gap": p.gap,
            "mate_in": mate if mate and mate > 0 else None,
            "best_line_san": p.best_line_san,
            "difficulty_note": "heuristic from mate distance or best-move margin",
            "game_move": {
                "san": p.played_san,
                "uci": p.played_uci,
                "eval_after": p.eval_after_text,
            },
            "hints": hints,
        },
    )


def side_to_move(fen: str) -> str:
    return "white" if chess.Board(fen).turn == chess.WHITE else "black"


def parse_move(fen: str, text: str) -> chess.Move | None:
    """Accept UCI (from a board UI) or SAN (typed). None if unparseable or illegal."""
    board = chess.Board(fen)
    text = text.strip()
    try:
        move = chess.Move.from_uci(text)
        if move in board.legal_moves:
            return move
    except ValueError:
        pass
    try:
        return board.parse_san(text)
    except ValueError:
        return None


def to_san(fen: str, uci: str) -> str:
    board = chess.Board(fen)
    return board.san(chess.Move.from_uci(uci))
