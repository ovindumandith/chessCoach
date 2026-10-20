"""Blinded comparison of coaching systems on the same evidence (project.md §26).

  A  engine only: the student's critical moves with the engine's best line
  B  rule-based personalised report: the deterministic template lesson
  C  evidence-grounded LLM lesson (only if LLM coaching is enabled)

`coaching_package` writes, per student, the reports in random order under neutral names
("Report 1".."Report 3"), a CSV rating sheet, and a SEPARATE key file. Coaches rate
without the key. `score_ratings` joins ratings and key and averages per system.
Nothing here is shown to students or stored as a coaching session.
"""

import csv
import json
import random
import uuid
from collections import defaultdict
from pathlib import Path

from sqlalchemy.orm import Session

from chesscoach.coaching.fallback import build_fallback
from chesscoach.coaching.providers import LLMError, get_provider
from chesscoach.coaching.retrieval import build_context, format_eval
from chesscoach.coaching.schemas import CoachingResponse, strict_json_schema
from chesscoach.coaching.service import load_prompt
from chesscoach.coaching.validation import validate_response
from chesscoach.core.config import get_settings
from chesscoach.core.errors import ConflictError
from chesscoach.evaluation.data import analyzed_games, student_ids
from chesscoach.evaluation.experiment import ExperimentConfig
from chesscoach.evaluation.metrics import mean

CRITERIA = [
    "chess_correctness",
    "evidence_traceability",
    "clarity",
    "personalization_relevance",
    "exercise_relevance",
]


def engine_only_report(db: Session, student_id: uuid.UUID | str, limit: int = 5) -> str:
    critical = []
    for game, moves in analyzed_games(db, uuid.UUID(str(student_id))):
        for m in moves:
            if (m.features or {}).get("critical"):
                critical.append((m.win_prob_loss or 0, game, m))
    critical.sort(key=lambda x: -x[0])
    lines = ["Engine report: your most costly moves."]
    for _, game, m in critical[:limit]:
        line = " ".join((m.features or {}).get("pv_san", [])[:5])
        lines.append(
            f"- {game.white_name} vs {game.black_name}, move {(m.ply + 1) // 2}: you played "
            f"{m.san_move} ({format_eval(m.eval_before_cp, m.eval_before_mate)} -> "
            f"{format_eval(m.eval_after_cp, m.eval_after_mate, after_move=True)}). "
            f"Engine: {line or 'n/a'}."
        )
    if len(lines) == 1:
        lines.append("- No critical moves found.")
    return "\n".join(lines)


def lesson_text(lesson: CoachingResponse) -> str:
    parts = [f"Objective: {lesson.objective}", lesson.recurring_pattern]
    parts += [f"Example: {e.explanation}" for e in lesson.examples]
    parts += [
        f"Question: {lesson.student_question}",
        f"Practice: {lesson.exercise_recommendation}",
        f"Follow-up: {lesson.follow_up_metric}",
        f"Uncertainty: {lesson.uncertainty}",
    ]
    return "\n".join(parts)


def coaching_package(db: Session, config: ExperimentConfig, out_dir: Path) -> tuple[dict, dict]:
    rng = random.Random(config.seed)
    provider = get_provider(get_settings())
    out_dir.mkdir(parents=True, exist_ok=True)
    packages, key, skipped, llm_stats = [], [], [], defaultdict(int)

    for sid in student_ids(db, config.student_ids):
        try:
            ctx = build_context(db, sid)
        except ConflictError as exc:
            skipped.append({"student_id": str(sid), "reason": exc.message})
            continue
        reports = {"A": engine_only_report(db, sid), "B": lesson_text(build_fallback(ctx))}
        if provider is not None:
            try:
                result = provider.generate(
                    system=load_prompt(),
                    user=json.dumps({"context": ctx.model_dump()}, sort_keys=True),
                    schema=strict_json_schema(CoachingResponse),
                )
                lesson = CoachingResponse.model_validate(result.data)
                errors = validate_response(lesson, ctx)
                llm_stats["validated" if not errors else "failed_validation"] += 1
                if not errors:  # never rate an unvalidated lesson
                    reports["C"] = lesson_text(lesson)
            except (LLMError, ValueError) as exc:
                llm_stats["provider_errors"] += 1
                skipped.append({"student_id": str(sid), "reason": f"C unavailable: {exc}"})
        systems = list(reports)
        rng.shuffle(systems)
        blinded = {f"Report {i}": reports[s] for i, s in enumerate(systems, 1)}
        packages.append(
            {
                "student_id": str(sid),
                "objective_skill": ctx.objective.skill_name,
                "reports": blinded,
            }
        )
        key += [
            {"student_id": str(sid), "report": f"Report {i}", "system": s}
            for i, s in enumerate(systems, 1)
        ]

    (out_dir / "package.json").write_text(json.dumps(packages, indent=2), encoding="utf-8")
    with (out_dir / "ratings.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["student_id", "report", *CRITERIA, "comment"])
        w.writeheader()
        for p in packages:
            for name in p["reports"]:
                w.writerow({"student_id": p["student_id"], "report": name})
    (out_dir / "KEY_do_not_share_with_raters.json").write_text(
        json.dumps(key, indent=2), encoding="utf-8"
    )
    results = {
        "students": len(packages),
        "skipped": skipped,
        "llm": dict(llm_stats),
        "llm_enabled": provider is not None,
        "files": str(out_dir),
        "rating_scale": "1 (poor) - 5 (excellent) per criterion",
    }
    return results, {"student_ids": [p["student_id"] for p in packages]}


def score_ratings(ratings_csv: Path, key_json: Path) -> tuple[dict, dict]:
    key = {
        (k["student_id"], k["report"]): k["system"]
        for k in json.loads(key_json.read_text(encoding="utf-8"))
    }
    scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    unmatched = 0
    with ratings_csv.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            system = key.get((row["student_id"], row["report"]))
            if system is None:
                unmatched += 1
                continue
            for c in CRITERIA:
                if (row.get(c) or "").strip():
                    scores[system][c].append(float(row[c]))
    results = {
        "per_system": {
            s: {c: {"mean": mean(v), "n": len(v)} for c, v in crit.items()}
            for s, crit in sorted(scores.items())
        },
        "unmatched_rows": unmatched,
        "systems": {"A": "engine only", "B": "rule-based template", "C": "LLM grounded"},
    }
    return results, {"ratings_file": str(ratings_csv)}
