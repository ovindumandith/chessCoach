"""Chess and evidence validation of LLM coaching output. Pydantic checks structure only.

Every check compares the response with the stored evidence that was supplied in the
context. Any failure means the response is not shown to the student.
"""

import re

import chess

from chesscoach.coaching.schemas import CoachingContext, CoachingResponse

MAX_EXAMPLES = 2

# SAN that cannot be mistaken for a square name: piece moves, captures, checks, castling.
# Bare pawn pushes ("e4") are skipped because they read the same as squares.
_SAN = re.compile(
    r"(?<![\w-])(O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8][+#]?|[a-h]x[a-h][1-8](?:=[QRBN])?[+#]?"
    r"|[a-h][1-8](?:=[QRBN])?[+#])(?![\w-])"
)
_EVAL = re.compile(r"(?<![\w.])([+-]\d{1,2}\.\d{1,2})(?![\d])")
_MATE = re.compile(r"\bmat(?:e|ed) in (\d+)\b", re.IGNORECASE)


def _norm(san: str) -> str:
    return san.rstrip("+#!?")


def _texts(r: CoachingResponse) -> list[str]:
    return [
        r.objective,
        r.recurring_pattern,
        r.student_question,
        r.exercise_recommendation,
        r.follow_up_metric,
        r.uncertainty,
        *r.verified_facts,
        *r.hypotheses,
        *(e.explanation for e in r.examples),
    ]


def validate_response(r: CoachingResponse, ctx: CoachingContext) -> list[str]:
    errors: list[str] = []
    positions = {(p.game_id, p.ply): p for p in ctx.positions}

    if r.skill_code != ctx.objective.skill_code:
        errors.append(
            f"skill_code {r.skill_code!r} is not the objective {ctx.objective.skill_code!r}"
        )

    if not 1 <= len(r.examples) <= MAX_EXAMPLES:
        errors.append(f"expected 1-{MAX_EXAMPLES} examples, got {len(r.examples)}")
    for ex in r.examples:
        pos = positions.get((ex.game_id, ex.ply))
        if pos is None:
            errors.append(
                f"example references an unknown position (game {ex.game_id}, ply {ex.ply})"
            )
            continue
        if ex.fen != pos.fen:
            errors.append(f"example FEN does not match the stored position at ply {ex.ply}")
        if ex.engine_best_move_uci is not None:
            board = chess.Board(pos.fen)
            try:
                move = chess.Move.from_uci(ex.engine_best_move_uci)
            except ValueError:
                move = None
            if move is None or move not in board.legal_moves:
                errors.append(
                    f"suggested move {ex.engine_best_move_uci!r} is not legal at ply {ex.ply}"
                )
            elif ex.engine_best_move_uci != pos.engine_best_move_uci:
                errors.append(
                    f"claimed engine move {ex.engine_best_move_uci!r} differs from "
                    f"the stored engine move at ply {ex.ply}"
                )

    allowed_moves = set()
    for p in ctx.positions:
        allowed_moves.update(
            _norm(s)
            for s in [p.played_move_san, *p.engine_best_line_san, *p.opponent_best_reply_san]
        )
    for text in _texts(r):
        for san in _SAN.findall(text):
            if _norm(san) not in allowed_moves:
                errors.append(f"move {san!r} does not appear in the supplied evidence")

    # The question must make the student calculate, not hand them the answer.
    for ex in r.examples:
        pos = positions.get((ex.game_id, ex.ply))
        best = pos.engine_best_move_san if pos else None
        if (
            best
            and best != pos.played_move_san
            and re.search(rf"(?<![\w-]){re.escape(_norm(best))}(?![\w-])", r.student_question)
        ):
            errors.append("student_question reveals the solution")

    stored_evals = set()
    stored_mates = set()
    for p in ctx.positions:
        for value in (p.eval_before, p.eval_after):
            if value.startswith(("+", "-")):
                stored_evals.add(round(float(value), 2))
            for n in re.findall(r"\d+", value) if "mate" in value else []:
                stored_mates.add(int(n))
    for text in _texts(r):
        for raw in _EVAL.findall(text):
            if round(float(raw), 2) not in stored_evals:
                errors.append(f"evaluation {raw} does not match any supplied evaluation")
        for n in _MATE.findall(text):
            if int(n) not in stored_mates:
                errors.append(f"'mate in {n}' does not match the supplied evaluations")

    return sorted(set(errors))
