"""Predictive validity of student profiles (temporal hold-out, project.md §26-27).

For each student with enough games on both sides of the cutoff:
- build a profile IN MEMORY from games played strictly before the cutoff (nothing is
  persisted, and later games are never visible to it);
- take its top-k actionable skills by training priority as the prediction;
- "relevant" = skills with a classified error in at least one game ON/AFTER the cutoff.

Compared with a non-personalised baseline: the k skills most frequent across ALL
students' pre-cutoff evidence. If personal profiles are useful, they should beat it.
With 10-30 students this is pilot evidence, not proof.
"""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.classification.classifier import CLASSIFIER_VERSION
from chesscoach.classification.taxonomy import UNCLASSIFIED, get_taxonomy
from chesscoach.db.enums import ReviewStatus
from chesscoach.db.models import WeaknessObservation
from chesscoach.evaluation.data import analyzed_games, label_of, student_ids
from chesscoach.evaluation.experiment import ExperimentConfig
from chesscoach.evaluation.metrics import mean, precision_at_k
from chesscoach.profiling.aggregator import build_profile
from chesscoach.profiling.service import gather_facts


def _errors_by_game(db: Session, game_ids) -> dict:
    out: dict = {}
    rows = db.scalars(
        select(WeaknessObservation).where(
            WeaknessObservation.game_id.in_(game_ids),
            WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
            WeaknessObservation.review_status != ReviewStatus.REJECTED,
        )
    )
    for o in rows:
        if o.skill_code != UNCLASSIFIED:
            out.setdefault(o.game_id, set()).add(label_of(o.skill_code, o.subskill_code))
    return out


def predictive_validity(db: Session, config: ExperimentConfig) -> tuple[dict, dict]:
    if config.cutoff_date is None:
        raise ValueError("predictive validity needs cutoff_date in the experiment config")
    cutoff, k = config.cutoff_date, config.k
    taxonomy = get_taxonomy()

    eligible, population = [], Counter()
    for sid in student_ids(db, config.student_ids):
        games = analyzed_games(db, sid)
        before = [g for g, _ in games if g.played_at and g.played_at < cutoff]
        after = [g for g, _ in games if g.played_at and g.played_at >= cutoff]
        errors = _errors_by_game(db, [g.id for g in before + after])
        for g in before:  # population baseline: pre-cutoff evidence only
            population.update(errors.get(g.id, set()))
        if len(before) >= config.min_games_before and len(after) >= config.min_games_after:
            eligible.append((sid, before, after, errors))
    baseline_rank = [label for label, _ in population.most_common()]

    per_student = []
    for sid, before, after, errors in eligible:
        facts = gather_facts(db, sid, cutoff=cutoff)
        profile = build_profile(
            taxonomy,
            facts.moves,
            facts.observations,
            facts.opportunities,
            games_included=facts.games_included,
            exercises=facts.exercises,
        )
        predicted = [
            label_of(s.skill_code, s.subskill_code)
            for s in profile.skills
            if s.priority and s.error_count > 0 and s.skill_code != UNCLASSIFIED
        ]
        future = set().union(*(errors.get(g.id, set()) for g in after))
        per_student.append(
            {
                "student_id": str(sid),
                "games_before": len(before),
                "games_after": len(after),
                "predicted_top_k": predicted[:k],
                "future_skills": sorted(future),
                "profile_precision_at_k": precision_at_k(predicted, future, k),
                "baseline_precision_at_k": precision_at_k(baseline_rank, future, k),
            }
        )

    results = {
        "k": k,
        "cutoff_date": str(cutoff),
        "students_evaluated": len(per_student),
        "mean_profile_precision_at_k": mean(s["profile_precision_at_k"] for s in per_student),
        "mean_baseline_precision_at_k": mean(s["baseline_precision_at_k"] for s in per_student),
        "baseline_ranking": baseline_rank[:10],
        "per_student": per_student,
        "caveat": "Pilot-scale evidence; future 'errors' are classifier output, so they share "
        "its biases. Use coach-confirmed findings for stronger claims.",
    }
    dataset = {
        "student_ids": [s["student_id"] for s in per_student],
        "game_ids_before": sorted(str(g.id) for _, b, _, _ in eligible for g in b),
        "game_ids_after": sorted(str(g.id) for _, _, a, _ in eligible for g in a),
    }
    return results, dataset
