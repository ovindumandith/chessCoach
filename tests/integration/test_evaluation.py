"""Research evaluation studies on a small analyzed dataset."""

import csv
import json
from datetime import date

import pytest
from sqlalchemy import func, select

from chesscoach.analysis.worker import run_once
from chesscoach.core.config import Settings
from chesscoach.db.models import ProfileSnapshot, WeaknessObservation
from chesscoach.evaluation import benchmark, comparison, predictive
from chesscoach.evaluation.experiment import ExperimentConfig, record
from tests.fakes import FakeAnalyzer
from tests.integration.test_profiles import PGN  # same missed mate in games dated Jan-Mar 2024

API = "/api/v1"


@pytest.fixture
def dataset(client, db):
    s = client.post(f"{API}/students", json={"display_name": "S", "aliases": ["Ovindu"]}).json()
    report = client.post(
        f"{API}/students/{s['id']}/games/import",
        headers=client.as_student(s["id"]),
        files={"file": ("g.pgn", PGN, "application/x-chess-pgn")},
    ).json()
    for g in report["games"]:
        client.post(
            f"{API}/games/{g['game_id']}/analyze", headers=client.as_student.game(g["game_id"])
        )
    while run_once(db, FakeAnalyzer(), Settings(stockfish_depth=8), "w"):
        pass
    return s


def cfg(**kw):
    return ExperimentConfig(name="t", **kw)


def test_annotation_template_is_blind_stratified_and_reproducible(db, dataset, tmp_path):
    info = benchmark.annotation_template(
        db, cfg(sample_flagged=5, sample_unflagged=5), tmp_path / "a.csv"
    )
    rows = list(csv.DictReader((tmp_path / "a.csv").open(encoding="utf-8")))
    assert info["items"] == len(rows) and info["flagged_available"] > 0
    assert info["unflagged_available"] > 0
    assert all(r["gold_labels"] == "" and r["is_error"] == "" for r in rows)
    header = rows[0].keys()
    assert not any("skill" in h or "label" in h and h != "gold_labels" for h in header)
    assert "tactical_awareness" not in (tmp_path / "a.csv").read_text(encoding="utf-8")
    benchmark.annotation_template(db, cfg(sample_flagged=5, sample_unflagged=5), tmp_path / "b.csv")
    assert (tmp_path / "a.csv").read_text() == (tmp_path / "b.csv").read_text()


def test_benchmark_scores_original_classifier_output(db, dataset, tmp_path):
    benchmark.annotation_template(
        db, cfg(sample_flagged=50, sample_unflagged=50), tmp_path / "gold.csv"
    )
    rows = list(csv.DictReader((tmp_path / "gold.csv").open(encoding="utf-8")))
    for r in rows:  # a coach marks every Qe2 as a missed mating pattern, nothing else
        missed = r["move_played"] == "Qe2"
        r["gold_labels"] = "tactical_awareness.mating_patterns" if missed else ""
        r["is_error"] = "yes" if missed else "no"
    with (tmp_path / "gold.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=benchmark.TEMPLATE_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    results, data = benchmark.score_benchmark(db, tmp_path / "gold.csv")
    mate = results["skill_labels"]["labels"]["tactical_awareness.mating_patterns"]
    assert mate["recall"] == 1.0 and mate["precision"] == 1.0
    assert results["critical_move_detection"]["recall"] == 1.0
    assert results["items_not_found"] == 0
    assert results["skill_labels"]["macro_f1"] is not None
    # Extra labels the classifier added on the same move count as false positives.
    extras = [
        v
        for k, v in results["skill_labels"]["labels"].items()
        if k != "tactical_awareness.mating_patterns"
    ]
    assert all(v["tp"] == 0 and v["f1"] == 0.0 for v in extras)


def test_review_precision(client, db, dataset):
    items = client.get(
        f"{API}/students/{dataset['id']}/weaknesses", params={"skill_code": "tactical_awareness"}
    ).json()["items"]
    client.patch(
        f"{API}/observations/{items[0]['id']}/review",
        json={"action": "confirm"},
        headers=client.as_admin,
    )
    client.patch(
        f"{API}/observations/{items[1]['id']}/review",
        json={"action": "reject"},
        headers=client.as_admin,
    )
    results, _ = benchmark.review_precision(db, cfg())
    label = results["per_label"]["tactical_awareness.mating_patterns"]
    assert (label["reviewed"], label["confirmed"], label["precision"]) == (2, 1, 0.5)
    assert "precision only" in results["caveat"]


def test_predictive_validity_uses_only_pre_cutoff_games(db, dataset):
    snapshots_before = db.scalar(select(func.count()).select_from(ProfileSnapshot))
    results, data = predictive.predictive_validity(
        db, cfg(cutoff_date=date(2024, 2, 1), min_games_before=1, min_games_after=1)
    )
    assert results["students_evaluated"] == 1
    s = results["per_student"][0]
    assert (s["games_before"], s["games_after"]) == (1, 2)
    assert "tactical_awareness.mating_patterns" in s["predicted_top_k"]
    assert "tactical_awareness.mating_patterns" in s["future_skills"]
    assert s["profile_precision_at_k"] > 0
    assert len(data["game_ids_before"]) == 1 and len(data["game_ids_after"]) == 2
    # Research runs never write live profile snapshots.
    assert db.scalar(select(func.count()).select_from(ProfileSnapshot)) == snapshots_before


def test_predictive_requires_a_cutoff(db, dataset):
    with pytest.raises(ValueError):
        predictive.predictive_validity(db, cfg())


def test_coaching_package_is_blinded_and_scorable(db, dataset, tmp_path):
    sessions_before = db.scalar(select(func.count()).select_from(WeaknessObservation))
    results, data = comparison.coaching_package(db, cfg(), tmp_path)
    assert results["students"] == 1 and results["llm_enabled"] is False
    package = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    reports = package[0]["reports"]
    assert set(reports) == {"Report 1", "Report 2"}  # A and B; C needs an LLM
    assert "System" not in json.dumps(package)
    key = json.loads((tmp_path / "KEY_do_not_share_with_raters.json").read_text())
    assert {k["system"] for k in key} == {"A", "B"}

    rows = list(csv.DictReader((tmp_path / "ratings.csv").open(encoding="utf-8")))
    system_of = {(k["student_id"], k["report"]): k["system"] for k in key}
    for r in rows:
        score = "2" if system_of[(r["student_id"], r["report"])] == "A" else "4"
        for c in comparison.CRITERIA:
            r[c] = score
    with (tmp_path / "ratings.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["student_id", "report", *comparison.CRITERIA, "comment"])
        w.writeheader()
        w.writerows(rows)
    scored, _ = comparison.score_ratings(
        tmp_path / "ratings.csv", tmp_path / "KEY_do_not_share_with_raters.json"
    )
    assert scored["per_system"]["A"]["clarity"] == {"mean": 2.0, "n": 1}
    assert scored["per_system"]["B"]["clarity"] == {"mean": 4.0, "n": 1}
    assert db.scalar(select(func.count()).select_from(WeaknessObservation)) == sessions_before


def test_engine_only_report_lists_critical_moves(db, dataset):
    text = comparison.engine_only_report(db, dataset["id"])
    assert "you played Qe2" in text and "Qxf7#" in text


def test_record_is_reproducible_and_secret_free(tmp_path):
    path = record("benchmark", cfg(seed=3), {"game_ids": ["g1"]}, {"x": 1}, out_dir=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["versions"]["classifier"] == "classifier-v2"
    assert payload["versions"]["profile"] == "profile-v1"
    assert payload["code_revision"] and payload["config"]["seed"] == 3
    assert payload["dataset"] == {"game_ids": ["g1"]}
    for secret in ("app_secret_key", "llm_api_key", "database_url"):
        assert secret not in payload["settings"]
