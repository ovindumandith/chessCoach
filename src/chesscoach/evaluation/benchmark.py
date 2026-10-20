"""Classifier benchmark against independent coach annotations (project.md §26).

1. `annotation_template` exports a BLIND sample of student moves: engine facts only, never
   the classifier's labels, so annotators are not anchored. It is stratified: flagged
   moves (the classifier said something) and unflagged moves (it said nothing). Without
   unflagged moves, recall cannot be measured.
2. Coaches fill in `gold_labels` (taxonomy codes, `;`-separated, empty = no skill issue)
   and `is_error` (yes/no).
3. `score_benchmark` compares the classifier's ORIGINAL output with the gold labels:
   per-label precision, recall, F1 and macro-F1, plus critical-move detection.

`review_precision` is a weaker, always-available signal: of the findings coaches
reviewed in the app, how many did they confirm? Reviews only see what the classifier
flagged, so they measure precision only, never recall.
"""

import csv
import random
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.classification.classifier import CLASSIFIER_VERSION
from chesscoach.classification.service import latest_evidence
from chesscoach.coaching.retrieval import format_eval
from chesscoach.core.errors import ConflictError
from chesscoach.db.enums import ReviewStatus
from chesscoach.db.models import Game, WeaknessObservation
from chesscoach.evaluation.data import analyzed_games, classifier_labels, label_of, student_ids
from chesscoach.evaluation.experiment import ExperimentConfig
from chesscoach.evaluation.metrics import binary_report, multilabel_report

TEMPLATE_COLUMNS = [
    "item_id",
    "game_id",
    "ply",
    "move_number",
    "side",
    "fen",
    "move_played",
    "eval_before",
    "eval_after",
    "engine_best_line",
    "gold_labels",
    "is_error",
    "notes",
]


def annotation_template(db: Session, config: ExperimentConfig, out: Path) -> dict:
    rng = random.Random(config.seed)
    flagged, unflagged = [], []
    for sid in student_ids(db, config.student_ids):
        games = analyzed_games(db, sid)
        labels = classifier_labels(db, [g.id for g, _ in games])
        for game, moves in games:
            for m in moves:
                if (m.features or {}).get("legal_moves") == 1:
                    continue  # forced moves are never classified
                (flagged if m.id in labels else unflagged).append((game, m))
    sample = rng.sample(flagged, min(config.sample_flagged, len(flagged))) + rng.sample(
        unflagged, min(config.sample_unflagged, len(unflagged))
    )
    rng.shuffle(sample)  # annotators must not be able to tell the strata apart

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TEMPLATE_COLUMNS)
        w.writeheader()
        for i, (game, m) in enumerate(sample, 1):
            w.writerow(
                {
                    "item_id": i,
                    "game_id": str(game.id),
                    "ply": m.ply,
                    "move_number": (m.ply + 1) // 2,
                    "side": game.student_color.value if game.student_color else "",
                    "fen": m.fen_before,
                    "move_played": m.san_move,
                    "eval_before": format_eval(m.eval_before_cp, m.eval_before_mate),
                    "eval_after": format_eval(m.eval_after_cp, m.eval_after_mate, after_move=True),
                    "engine_best_line": " ".join((m.features or {}).get("pv_san", [])[:6]),
                    "gold_labels": "",
                    "is_error": "",
                    "notes": "",
                }
            )
    return {
        "items": len(sample),
        "flagged_available": len(flagged),
        "unflagged_available": len(unflagged),
        "file": str(out),
        "game_ids": sorted({str(g.id) for g, _ in sample}),
    }


def score_benchmark(db: Session, gold_csv: Path) -> tuple[dict, dict]:
    with gold_csv.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("is_error") or r.get("gold_labels"))]
    by_game: dict[str, list[dict]] = {}
    for r in rows:
        by_game.setdefault(r["game_id"], []).append(r)

    label_pairs, critical_pairs, missing = [], [], 0
    for game_id, items in by_game.items():
        gid = uuid.UUID(game_id)
        moves = {m.ply: m for m in _latest_moves(db, gid)}
        predicted = classifier_labels(db, [gid])
        for r in items:
            m = moves.get(int(r["ply"]))
            if m is None:
                missing += 1  # game re-analyzed or deleted since annotation
                continue
            gold = {x.strip() for x in (r.get("gold_labels") or "").split(";") if x.strip()}
            label_pairs.append((gold, predicted.get(m.id, set())))
            if r.get("is_error", "").strip().lower() in ("yes", "no"):
                critical_pairs.append(
                    (
                        r["is_error"].strip().lower() == "yes",
                        bool((m.features or {}).get("critical")),
                    )
                )
    results = {
        "classifier_version": CLASSIFIER_VERSION,
        "skill_labels": multilabel_report(label_pairs),
        "critical_move_detection": binary_report(critical_pairs),
        "annotated_items": len(rows),
        "items_not_found": missing,
        "note": "Predictions are the classifier's original labels, before coach review.",
    }
    return results, {"game_ids": sorted(by_game), "gold_file": str(gold_csv)}


def review_precision(db: Session, config: ExperimentConfig) -> tuple[dict, dict]:
    sids = student_ids(db, config.student_ids)
    rows = db.scalars(
        select(WeaknessObservation).where(
            WeaknessObservation.student_id.in_(sids),
            WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
            WeaknessObservation.review_status != ReviewStatus.CANDIDATE,
        )
    )
    confirmed, reviewed, by_type = Counter(), Counter(), Counter()
    for o in rows:
        original = o.details.get("original")
        label = (
            label_of(original["skill_code"], original["subskill_code"])
            if original
            else label_of(o.skill_code, o.subskill_code)
        )
        reviewed[label] += 1
        by_type[(o.evidence_type.value, o.review_status.value)] += 1
        if o.review_status == ReviewStatus.CONFIRMED:
            confirmed[label] += 1
    per_label = {
        label: {
            "reviewed": n,
            "confirmed": confirmed[label],
            "precision": round(confirmed[label] / n, 4),
        }
        for label, n in sorted(reviewed.items())
    }
    total = sum(reviewed.values())
    results = {
        "per_label": per_label,
        "overall_precision": round(sum(confirmed.values()) / total, 4) if total else None,
        "reviewed": total,
        "by_evidence_type": {f"{t}:{s}": n for (t, s), n in sorted(by_type.items())},
        "caveat": "Reviews only see flagged moves: this is precision only, not recall, "
        "and reviewers saw the classifier's label (not blind).",
    }
    return results, {"student_ids": [str(s) for s in sids]}


def _latest_moves(db: Session, game_id: uuid.UUID) -> list:
    game = db.get(Game, game_id)
    if game is None:
        return []
    try:
        return latest_evidence(db, game)[2]
    except ConflictError:
        return []
