"""The "Chess LLM" improvement plan: all analyzed games -> LLM -> a detailed, checked plan.

Flow: build a context from every analyzed game (moves, the student's mistakes with
Stockfish's evaluations, better moves and reasons, the skill profile and puzzle ratings),
ask the LLM for a structured plan, check it against that context, retry once with the
reasons, otherwise build a deterministic template plan from the same evidence. Every
plan is stored with exactly what was sent, so it can be reproduced and audited.

Stockfish stays the only authority on moves: the plan may cite only supplied mistakes and
may mention only moves that appear in the supplied games or engine lines.
"""

import hashlib
import io
import json
import logging
import re
import uuid
from collections import Counter

import chess.pgn
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.analysis.service import analysis_states
from chesscoach.classification.taxonomy import UNCLASSIFIED, get_taxonomy
from chesscoach.coaching.providers import LLMError, LLMProvider, get_provider
from chesscoach.coaching.schemas import _Strict, strict_json_schema
from chesscoach.coaching.service import load_prompt
from chesscoach.core.access import require_own_student_record, require_student_access
from chesscoach.core.audit import record_audit
from chesscoach.core.config import Settings, get_settings
from chesscoach.core.errors import ConflictError, NotFoundError
from chesscoach.db.enums import Color, MappingStatus, ValidationStatus
from chesscoach.db.models import (
    Game,
    ImprovementPlan,
    ProfileSnapshot,
    Student,
    StudentPuzzleRating,
    User,
)
from chesscoach.mistakes import student_mistakes
from chesscoach.puzzles.themes import LICHESS_THEMES, get_theme_map

log = logging.getLogger("chesscoach.plan")

PROMPT_VERSION = "improvement_plan_v2"  # v2: short sentences a child understands
TEMPLATE_VERSION = "plan-template-v2"  # v2: short, child-friendly wording
CONTEXT_VERSION = "plan-context-v2"  # v2: allowed skills as explicit pairs
# Only fully analyzed games: findings exist once the deeper check has finished.
COMPLETE = "analyzed"
IN_PROGRESS = ("queued", "running", "deepening")
RESOLVED = (MappingStatus.MAPPED, MappingStatus.CONFIRMED)
MAX_GAMES = 60  # newest first
MOVES_FOR_RECENT = 20  # full move lists for the most recent games
MAX_CONTEXT_CHARS = 120_000  # about 30k tokens; older games are trimmed beyond this


# --------------------------------------------------------------------------- response schema


class PlanEvidence(_Strict):
    game_id: str
    ply: int


class PlanWeakness(_Strict):
    skill_code: str
    subskill_code: str | None
    title: str
    explanation: str
    evidence: list[PlanEvidence]


class PlanStep(_Strict):
    period: str  # e.g. "Weeks 1-2"
    focus: str
    activities: list[str]
    goal: str


class ImprovementPlanResponse(_Strict):
    title: str
    summary: str
    strengths: list[str]
    weaknesses: list[PlanWeakness]
    plan: list[PlanStep]
    training_routine: list[str]
    puzzle_themes: list[str]
    study_topics: list[str]
    habits: list[str]
    milestones: list[str]
    uncertainty: str


def response_schema() -> dict:
    return strict_json_schema(ImprovementPlanResponse)


# --------------------------------------------------------------------------- context


def game_counts(db: Session, student_id: uuid.UUID) -> tuple[int, int]:
    """(fully analyzed games, games still being analyzed)."""
    ids = list(
        db.scalars(
            select(Game.id).where(Game.student_id == student_id, Game.mapping_status.in_(RESOLVED))
        )
    )
    states = list(analysis_states(db, ids).values())
    return sum(s == COMPLETE for s in states), sum(s in IN_PROGRESS for s in states)


def _pov(e: dict | None, white: bool) -> str | None:
    """A White-POV evaluation as text from the student's side."""
    if not e:
        return None
    if e.get("mate") is not None:
        if e["mate"] == 0:
            return "checkmate on the board"
        m = e["mate"] if white else -e["mate"]
        return f"mate in {m} for you" if m > 0 else f"you get mated in {-m}"
    if e.get("cp") is None:
        return None
    cp = e["cp"] if white else -e["cp"]
    return f"{cp / 100:+.2f}"


def _moves_text(raw_pgn: str) -> str | None:
    game = chess.pgn.read_game(io.StringIO(raw_pgn))
    if game is None:
        return None
    board = game.board()
    parts = []
    for node in game.mainline():
        if board.turn == chess.WHITE:
            parts.append(f"{board.fullmove_number}.")
        parts.append(board.san(node.move))
        board.push(node.move)
    return " ".join(parts)


def _result_for(result: str, white: bool) -> str:
    if result == "1/2-1/2":
        return "draw"
    if result in ("1-0", "0-1"):
        return "win" if (result == "1-0") == white else "loss"
    return "unknown"


def build_context(db: Session, user: User, student_id: uuid.UUID) -> tuple[dict, dict]:
    """(context sent to the LLM, metadata about what was included)."""
    student = db.get(Student, student_id)
    page = student_mistakes(db, user, student_id, limit=10_000)
    complete = [g for g in page["games"] if not g["pending"]]
    total_complete = len(complete)
    complete = complete[:MAX_GAMES]
    games_by_id = {
        str(g.id): g
        for g in db.scalars(
            select(Game).where(Game.id.in_([uuid.UUID(x["game_id"]) for x in complete]))
        )
    }
    games = []
    for i, g in enumerate(complete):
        row = games_by_id[g["game_id"]]
        white = row.student_color == Color.WHITE
        games.append(
            {
                "game_id": g["game_id"],
                "date": g["played_at"],
                "you_played": g["student_color"],
                "opponent": g["opponent"],
                "result": _result_for(g["result"], white),
                "opening_eco": row.opening_eco,
                "time_control": row.time_control,
                "moves": _moves_text(row.raw_pgn) if i < MOVES_FOR_RECENT else None,
                "mistakes": [
                    {
                        "game_id": g["game_id"],
                        "ply": m["ply"],
                        "move_number": m["move_number"],
                        "move": m["san"],
                        "verdict": m["verdict"],
                        "eval_before": _pov(m["eval_before"], white),
                        "eval_after": _pov(m["eval_after"], white),
                        "better_move": m["best_move_san"],
                        "engine_line": m["best_line_san"][:6],
                        "reason": " ".join(m["reasons"]),
                        "kinds": [
                            {
                                "skill_code": t["skill_code"],
                                "subskill_code": t["subskill_code"],
                                "motif": t["motif_kind"],
                            }
                            for t in m["types"]
                        ],
                        "acknowledged": m["acknowledged_at"] is not None,
                        "same_kind_in_earlier_games": max(
                            (len(t["earlier"]) for t in m["types"]), default=0
                        ),
                    }
                    for m in g["mistakes"]
                ],
            }
        )

    taxonomy = get_taxonomy()
    skills = []
    snapshot = db.scalar(
        select(ProfileSnapshot)
        .where(ProfileSnapshot.student_id == student_id, ProfileSnapshot.cutoff_date.is_(None))
        .order_by(ProfileSnapshot.profile_version.desc())
        .limit(1)
    )
    if snapshot is not None:
        for s in snapshot.skills:
            if s.error_count == 0 and s.state.value != "no_issue_detected":
                continue
            skills.append(
                {
                    "skill_code": s.skill_code,
                    "subskill_code": s.subskill_code,
                    "state": s.state.value,
                    "errors": s.error_count,
                    "games_affected": s.games_affected,
                    "error_rate": round(s.error_rate, 4) if s.error_rate is not None else None,
                    "priority": round(s.priority_score, 4)
                    if s.priority_score is not None
                    else None,
                }
            )
        skills.sort(key=lambda s: -(s["priority"] or 0))

    puzzle_ratings = [
        {
            "skill_code": r.skill_code,
            "subskill_code": r.subskill_code,
            "rating": round(r.rating),
            "puzzles_decided": r.puzzles_decided,
        }
        for r in db.scalars(
            select(StudentPuzzleRating).where(StudentPuzzleRating.student_id == student_id)
        )
    ]
    # Explicit pairs: given "skill.subskill" strings, models put both into skill_code.
    allowed_skills = [{"skill_code": UNCLASSIFIED, "subskill_code": None}] + [
        {"skill_code": code, "subskill_code": sub}
        for code, cat in taxonomy.categories.items()
        for sub in cat.subskills
    ]

    def summary(gs: list[dict]) -> dict:
        mistakes = [m for g in gs for m in g["mistakes"]]
        return {
            "games_analyzed_total": total_complete,
            "games_included": len(gs),
            "results": dict(Counter(g["result"] for g in gs)),
            "mistakes_by_verdict": dict(Counter(m["verdict"] for m in mistakes)),
            "mistakes_acknowledged": sum(1 for m in mistakes if m["acknowledged"]),
            "repeated_kinds": sum(1 for m in mistakes if m["same_kind_in_earlier_games"]),
        }

    def assemble(gs: list[dict]) -> dict:
        return {
            "context_version": CONTEXT_VERSION,
            "student": {
                "level": student.skill_level,
                "rating_estimate": student.rating_estimate,
            },
            "summary": summary(gs),
            "skills": skills,
            "puzzle_ratings": puzzle_ratings,
            "games": gs,
            "allowed": {"skills": allowed_skills, "puzzle_themes": sorted(LICHESS_THEMES)},
        }

    # Keep the request a sensible size: drop move lists, then whole games, oldest first.
    ctx = assemble(games)
    while len(json.dumps(ctx)) > MAX_CONTEXT_CHARS and games:
        with_moves = [g for g in games if g["moves"]]
        if len(with_moves) > 5:
            with_moves[-1]["moves"] = None
        elif len(games) > 5:
            games.pop()
        else:
            break
        ctx = assemble(games)
    meta = {
        "games_total": total_complete,
        "games_included": len(games),
        "games_with_moves": sum(1 for g in games if g["moves"]),
        "truncated": len(games) < total_complete,
    }
    return ctx, meta


def context_hash(ctx: dict) -> str:
    return hashlib.sha256(json.dumps(ctx, sort_keys=True).encode()).hexdigest()


# --------------------------------------------------------------------------- validation

SAN = re.compile(
    r"(?<![A-Za-z0-9])(O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?"
    r"|[a-h]x[a-h][1-8](?:=[QRBN])?)[+#]?(?![A-Za-z0-9])"
)


def _known_moves(ctx: dict) -> set[str]:
    known: set[str] = set()
    for g in ctx["games"]:
        if g["moves"]:
            known.update(t for t in g["moves"].split() if not t.endswith("."))
        for m in g["mistakes"]:
            known.update(x for x in [m["move"], m["better_move"], *m["engine_line"]] if x)
    return {k.rstrip("+#") for k in known}


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def normalize_plan(plan: ImprovementPlanResponse) -> ImprovementPlanResponse:
    """Accept "skill.subskill" written into skill_code (with no subskill) when it names a
    valid taxonomy entry; anything else is left for validate_plan to report."""
    taxonomy = get_taxonomy()
    for w in plan.weaknesses:
        if w.subskill_code is None and "." in w.skill_code:
            skill, sub = w.skill_code.split(".", 1)
            if taxonomy.is_valid(skill, sub):
                w.skill_code, w.subskill_code = skill, sub
    return plan


def validate_plan(plan: ImprovementPlanResponse, ctx: dict) -> list[str]:
    errors: list[str] = []
    taxonomy = get_taxonomy()
    cited = {(m["game_id"], m["ply"]) for g in ctx["games"] for m in g["mistakes"]}
    if not plan.title.strip() or not plan.summary.strip():
        errors.append("title and summary must not be empty")
    if cited and not plan.weaknesses:
        errors.append("name at least one weakness from the supplied mistakes")
    if len(plan.plan) < 2:
        errors.append("the plan needs at least two steps")
    for w in plan.weaknesses:
        if not taxonomy.is_valid(w.skill_code, w.subskill_code):
            errors.append(f"unknown skill code {w.skill_code}.{w.subskill_code}")
        if not w.evidence:
            errors.append(f"weakness '{w.title}' cites no evidence")
        for e in w.evidence:
            if (e.game_id, e.ply) not in cited:
                errors.append(f"evidence game {e.game_id} ply {e.ply} is not a supplied mistake")
    for theme in plan.puzzle_themes:
        if theme not in LICHESS_THEMES:
            errors.append(f"unknown puzzle theme {theme}")
    known = _known_moves(ctx)
    invented = sorted(
        {
            m.group(0).rstrip("+#")
            for text in _strings(plan.model_dump())
            for m in SAN.finditer(text)
            if m.group(0).rstrip("+#") not in known
        }
    )
    if invented:
        errors.append(
            "mentions moves that are not in the supplied games or engine lines: "
            + ", ".join(invented[:10])
        )
    return errors


# --------------------------------------------------------------------------- template plan


def _times(n: int) -> str:
    return "once" if n == 1 else f"{n} times"


def build_template(ctx: dict, reason: str) -> ImprovementPlanResponse:
    """A deterministic plan from the same evidence, used when no LLM answer passes."""
    taxonomy = get_taxonomy()
    theme_map = get_theme_map()
    mistakes = [m for g in ctx["games"] for m in g["mistakes"]]

    def name(skill: str, sub: str | None) -> str:
        if skill in taxonomy.special:
            return taxonomy.special[skill].name
        cat = taxonomy.categories[skill]
        return cat.subskills[sub].name if sub else cat.name

    def rows_for(skill: str, sub: str | None) -> list[dict]:
        return [
            m
            for m in mistakes
            if any(k["skill_code"] == skill and k["subskill_code"] == sub for k in m["kinds"])
        ]

    def evidence_for(skill: str, sub: str | None) -> list[PlanEvidence]:
        return [PlanEvidence(game_id=m["game_id"], ply=m["ply"]) for m in rows_for(skill, sub)[:3]]

    focus = [
        (s["skill_code"], s["subskill_code"])
        for s in ctx["skills"]
        if s["errors"] and s["skill_code"] != UNCLASSIFIED
    ]
    if not focus:
        counts = Counter(
            (k["skill_code"], k["subskill_code"])
            for m in mistakes
            for k in m["kinds"]
            if k["skill_code"] != UNCLASSIFIED
        )
        focus = [key for key, _ in counts.most_common()]
    weaknesses = []
    for skill, sub in focus:
        ev = evidence_for(skill, sub)
        if ev and len(weaknesses) < 3:
            weaknesses.append(
                PlanWeakness(
                    skill_code=skill,
                    subskill_code=sub,
                    title=name(skill, sub),
                    explanation=(
                        f"This happened {_times(len(rows_for(skill, sub)))} in your games. "
                        "Look at the board to see the better move."
                    ),
                    evidence=ev,
                )
            )
    if not weaknesses and mistakes:
        weaknesses.append(
            PlanWeakness(
                skill_code=UNCLASSIFIED,
                subskill_code=None,
                title="Moves to check again",
                explanation="Stockfish found better moves here. Look at each one on the board.",
                evidence=[PlanEvidence(game_id=m["game_id"], ply=m["ply"]) for m in mistakes[:3]],
            )
        )
    themes: list[str] = []
    for w in weaknesses:
        for t in theme_map.themes_for(w.skill_code, w.subskill_code, "middlegame"):
            if t not in themes:
                themes.append(t)
    steps = [
        PlanStep(
            period=f"Week {i + 1}",
            focus=w.title,
            activities=[
                "Look at these mistakes on the board.",
                "Play 4 puzzles about it.",
                "Press Acknowledge when you understand it.",
            ],
            goal="Make this mistake less often in your next 5 games.",
        )
        for i, w in enumerate(weaknesses)
    ]
    steps.append(
        PlanStep(
            period=f"Week {len(weaknesses) + 1}",
            focus="Check your progress",
            activities=["Play 5 new games and add them here.", "Ask for a new plan."],
            goal="See how much you improved!",
        )
    )
    summary = ctx["summary"]
    return ImprovementPlanResponse(
        title="Your training plan",
        summary=(
            f"I looked at your {summary['games_included']} games and found "
            f"{len(mistakes)} moves to learn from."
        ),
        strengths=[
            name(s["skill_code"], s["subskill_code"])
            for s in ctx["skills"]
            if s["state"] == "no_issue_detected"
        ][:3]
        or ["Play more games so we can find your strengths."],
        weaknesses=weaknesses,
        plan=steps,
        training_routine=[
            "Every day: 10 minutes of puzzles.",
            "After each game: add it here and look at your mistakes.",
            "Once a week: replay a game you lost.",
        ],
        puzzle_themes=themes[:6],
        study_topics=[w.title for w in weaknesses],
        habits=[
            "Before every move, look for checks, captures and threats.",
            "When your opponent moves, ask: what does it attack?",
        ],
        milestones=[
            "5 new games with fewer big mistakes.",
            "Your puzzle rating goes up by 100 points.",
        ],
        uncertainty=(
            f"No AI wrote this plan ({reason}). It was made from your games with a template."
        ),
    )


# --------------------------------------------------------------------------- service


def plan_provider(settings: Settings) -> LLMProvider | None:
    """The configured LLM, with the plan model and token budget, or None when disabled."""
    if not settings.llm_enabled:
        return None
    return get_provider(
        settings.model_copy(
            update={
                "llm_model": settings.llm_plan_model or settings.llm_model,
                "llm_max_tokens": settings.llm_plan_max_tokens,
                "llm_timeout_seconds": settings.llm_plan_timeout_seconds,
            }
        )
    )


def _user_message(ctx: dict, feedback: list[str]) -> str:
    payload: dict = {"context": ctx}
    if feedback:
        payload["previous_attempt_rejected_because"] = feedback
    return json.dumps(payload, sort_keys=True)


def _positions(db: Session, p: ImprovementPlan) -> dict:
    """The board before each cited mistake, with the move played and the better move (UCI
    for arrows), taken from the stored game and the context the plan was made from."""
    ctx = p.context_json or {}
    mistakes = {
        (m["game_id"], m["ply"]): (g, m) for g in ctx.get("games", []) for m in g["mistakes"]
    }
    boards: dict[str, tuple[chess.Board, list]] = {}
    out: dict[str, dict] = {}
    for w in (p.response_json or {}).get("weaknesses", []):
        for e in w.get("evidence", [])[:3]:
            key = f"{e['game_id']}:{e['ply']}"
            found = mistakes.get((e["game_id"], e["ply"]))
            if key in out or found is None:
                continue
            g, m = found
            if e["game_id"] not in boards:
                game = db.get(Game, uuid.UUID(e["game_id"]))
                if game is None or game.student_id != p.student_id:
                    continue
                parsed = chess.pgn.read_game(io.StringIO(game.raw_pgn))
                if parsed is None:
                    continue
                boards[e["game_id"]] = (parsed.board(), list(parsed.mainline_moves()))
            start, moves = boards[e["game_id"]]
            board = start.copy()  # the game's own start (a PGN may begin from a FEN)
            for move in moves[: e["ply"] - 1]:
                board.push(move)

            def uci(san: str | None, b: chess.Board = board) -> str | None:
                try:
                    return b.parse_san(san).uci() if san else None
                except ValueError:
                    return None

            out[key] = {
                "fen": board.fen(),
                "played_san": m["move"],
                "played_uci": uci(m["move"]),
                "best_san": m["better_move"],
                "best_uci": uci(m["better_move"]),
                "move_number": m["move_number"],
                "verdict": m["verdict"],
                "opponent": g["opponent"],
                "date": g["date"],
                "you_played": g["you_played"],
            }
    return out


def plan_out(db: Session, p: ImprovementPlan, *, include_context: bool = False) -> dict:
    out = {
        "id": str(p.id),
        "student_id": str(p.student_id),
        "created_at": p.created_at.isoformat(),
        "model_provider": p.model_provider,
        "model_id": p.model_id,
        "prompt_version": p.prompt_version,
        "validation_status": p.validation_status.value,
        "validation_errors": p.validation_errors,
        "games_included": p.games_included,
        "games_total": p.games_total,
        "token_usage": p.token_usage,
        "latency_ms": p.latency_ms,
        "plan": p.response_json,
        "positions": _positions(db, p),
    }
    if include_context:
        out["context"] = p.context_json
    return out


def plan_overview(db: Session, user: User, student_id: uuid.UUID) -> dict:
    require_student_access(db, user, student_id)
    settings = get_settings()
    analyzed, in_progress = game_counts(db, student_id)
    plans = db.scalars(
        select(ImprovementPlan)
        .where(ImprovementPlan.student_id == student_id)
        .order_by(ImprovementPlan.created_at.desc())
    )
    return {
        "analyzed_games": analyzed,
        "games_in_progress": in_progress,
        "required_games": settings.plan_min_analyzed_games,
        "eligible": analyzed >= settings.plan_min_analyzed_games,
        "llm_enabled": settings.llm_enabled,
        "model": (settings.llm_plan_model or settings.llm_model) if settings.llm_enabled else None,
        "plans": [plan_out(db, p) for p in plans],
    }


def create_plan(
    db: Session, user: User, student_id: uuid.UUID, *, provider: LLMProvider | None = None
) -> ImprovementPlan:
    require_own_student_record(db, user, student_id)
    settings = get_settings()
    analyzed, _ = game_counts(db, student_id)
    if analyzed < settings.plan_min_analyzed_games:
        raise ConflictError(
            f"At least {settings.plan_min_analyzed_games} analyzed games are needed for a "
            f"recommendation; you have {analyzed}.",
            details={"analyzed_games": analyzed, "required": settings.plan_min_analyzed_games},
        )
    ctx, meta = build_context(db, user, student_id)
    provider = provider if provider is not None else plan_provider(settings)

    attempts: list[dict] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    latency = 0
    accepted: ImprovementPlanResponse | None = None
    served_model = None
    feedback: list[str] = []
    if provider is not None:
        for attempt in range(settings.llm_validation_retries + 1):
            record: dict = {"attempt": attempt + 1}
            try:
                result = provider.generate(
                    system=load_prompt(PROMPT_VERSION),
                    user=_user_message(ctx, feedback),
                    schema=response_schema(),
                )
            except LLMError as exc:
                record["error"] = str(exc)
                attempts.append(record)
                log.warning("Plan LLM call failed for student %s: %s", student_id, exc)
                break
            latency += result.latency_ms
            for k in usage:
                usage[k] += result.usage.get(k) or 0
            served_model = result.model
            record.update({"model": result.model, "usage": result.usage})
            try:
                candidate = normalize_plan(ImprovementPlanResponse.model_validate(result.data))
                errors = validate_plan(candidate, ctx)
            except ValidationError as exc:
                candidate, errors = None, [f"schema: {e['loc']} {e['msg']}" for e in exc.errors()]
            record["validation_errors"] = errors
            attempts.append(record)
            if not errors:
                accepted = candidate
                break
            feedback = errors

    used_fallback = accepted is None
    if used_fallback:
        reason = (
            "no AI model is configured"
            if provider is None
            else "the AI model's answer could not be used"
        )
        accepted = build_template(ctx, reason)
        final = validate_plan(accepted, ctx)
        if final:  # a template bug must never reach a student silently
            raise RuntimeError(f"Template plan failed validation: {final}")

    plan = ImprovementPlan(
        student_id=student_id,
        requested_by=user.id,
        model_provider="template" if used_fallback else provider.name,
        model_id=TEMPLATE_VERSION if used_fallback else (served_model or provider.model),
        prompt_version=PROMPT_VERSION,
        context_hash=context_hash(ctx),
        games_included=meta["games_included"],
        games_total=meta["games_total"],
        context_json=ctx,
        response_json=accepted.model_dump(),
        validation_status=ValidationStatus.FALLBACK if used_fallback else ValidationStatus.VALID,
        validation_errors=[e for a in attempts for e in a.get("validation_errors", [])]
        + [a["error"] for a in attempts if "error" in a],
        request_metadata={"llm_enabled": provider is not None, "attempts": attempts, **meta},
        token_usage=usage,
        latency_ms=latency or None,
    )
    db.add(plan)
    db.flush()
    record_audit(
        db,
        actor_user_id=user.id,
        action="coaching.plan",
        entity_type="improvement_plan",
        entity_id=plan.id,
        details={"student_id": str(student_id), "fallback": used_fallback, **meta},
    )
    db.commit()
    return plan


def get_plan(db: Session, user: User, plan_id: uuid.UUID, *, include_context: bool) -> dict:
    plan = db.get(ImprovementPlan, plan_id)
    if plan is None:
        raise NotFoundError("Recommendation not found")
    require_student_access(db, user, plan.student_id)
    return plan_out(db, plan, include_context=include_context)
