"""Deterministic, template-based lesson used when the LLM is disabled, unavailable, or its
output fails validation. Built only from stored evidence, so it is always grounded."""

from chesscoach.coaching.schemas import CoachingContext, CoachingResponse, LessonExample

TEMPLATE_VERSION = "template-v1"


def _example(p) -> LessonExample:
    side = "White" if p.student_color == "white" else "Black"
    best = (
        f" The engine preferred {p.engine_best_move_san}."
        if p.engine_best_move_san and p.engine_best_move_san != p.played_move_san
        else ""
    )
    reply = (
        f" The opponent's strongest reply was {p.opponent_best_reply_san[0]}."
        if p.opponent_best_reply_san
        else ""
    )
    return LessonExample(
        game_id=p.game_id,
        ply=p.ply,
        fen=p.fen,
        engine_best_move_uci=p.engine_best_move_uci if best else None,
        explanation=(
            f"Move {p.move_number} as {side}: you played {p.played_move_san} "
            f"({p.eval_before} before, {p.eval_after} after, measured from your side as "
            f"{side}: plus means you are better).{best}{reply}"
        ),
    )


def build_fallback(ctx: CoachingContext) -> CoachingResponse:
    o = ctx.objective
    chosen, games = [], set()
    for p in ctx.positions:
        if p.game_id not in games:
            chosen.append(p)
            games.add(p.game_id)
        if len(chosen) == 2:
            break
    uncertain = []
    if o.provisional:
        uncertain.append("Most of these findings have not been reviewed by a coach yet.")
    if o.games_affected < 3:
        uncertain.append(f"The pattern appears in only {o.games_affected} game(s) so far.")
    uncertain.append(
        "Engine analysis shows what happened on the board, not what you were "
        "thinking during the game."
    )
    return CoachingResponse(
        objective=f"Improve {o.skill_name.lower()}.",
        skill_code=o.skill_code,
        recurring_pattern=(
            f"This came up {o.error_count} time(s) across {o.games_affected} "
            f"game(s) in your analyzed games."
        ),
        examples=[_example(p) for p in chosen],
        student_question=(
            "Set up the first position on a board. Before moving, list every "
            "check, capture and threat for both sides. Which move would you "
            "play now, and why?"
        ),
        exercise_recommendation=(
            f"Solve a short set of positions that practise "
            f"{o.skill_name.lower()}, calculating each one fully before "
            f"checking the answer."
        ),
        follow_up_metric=(
            "Solve at least 4 of 5 new positions for this skill correctly, and "
            "watch whether the pattern recurs in your next 5 games."
        ),
        uncertainty=" ".join(uncertain),
        verified_facts=[
            f"{o.error_count} engine-confirmed instance(s) in {o.games_affected} game(s)."
        ],
        hypotheses=[f"Practising {o.skill_name.lower()} may reduce these errors."],
    )
