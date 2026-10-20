"""API -> job queue -> worker -> persisted analysis, using the deterministic fake engine."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from chesscoach.analysis.worker import claim_next_run, run_once
from chesscoach.core.config import Settings
from chesscoach.db.enums import AnalysisPass, JobStatus
from chesscoach.db.models import AnalysisRun, MoveAnalysis
from chesscoach.db.types import utcnow
from tests.fakes import FakeAnalyzer

API = "/api/v1"

MISSED_MATE_PGN = b"""[Event "Test"]
[White "Ovindu"]
[Black "Opp"]
[Result "*"]

1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qe2 *
"""


@pytest.fixture
def settings():
    return Settings(
        stockfish_depth=8,
        stockfish_critical_depth=12,
        analysis_multipv=2,
        analysis_critical_wp_loss=0.10,
        analysis_max_attempts=3,
        worker_stale_after_seconds=600,
    )


@pytest.fixture
def imported(client, mixed_pgn):
    student = client.post(
        f"{API}/students", json={"display_name": "Ovindu", "aliases": ["Ovindu", "ovindu_m"]}
    ).json()
    report = client.post(
        f"{API}/students/{student['id']}/games/import",
        files={"file": ("g.pgn", mixed_pgn, "application/x-chess-pgn")},
    ).json()
    games = {g["index"]: g["game_id"] for g in report["games"] if g["game_id"]}
    return student, games


def _upload(client, student_id, data, name):
    return client.post(
        f"{API}/students/{student_id}/games/import",
        files={"file": (name, data, "application/x-chess-pgn")},
    ).json()


def test_queue_process_and_read_analysis(client, db, imported, settings):
    _, games = imported
    resp = client.post(f"{API}/games/{games[0]}/analyze")
    assert resp.status_code == 202
    job = resp.json()
    assert job["status"] == "queued"

    # Before the worker runs, the analysis is not available yet.
    pending = client.get(f"{API}/games/{games[0]}/analysis")
    assert pending.status_code == 404
    assert pending.json()["error"]["details"]["latest_job_status"] == "queued"

    assert run_once(db, FakeAnalyzer(), settings, "test-worker") is True

    status = client.get(f"{API}/analysis-jobs/{job['id']}").json()
    assert status["status"] == "completed"
    assert status["engine_name"] == "FakeFish"
    assert status["configuration"]["analysis_version"] == "analysis-v2"
    assert status["configuration"]["depth"] == 8
    assert status["configuration"]["student_color"] == "white"

    analysis = client.get(f"{API}/games/{games[0]}/analysis").json()
    assert [m["ply"] for m in analysis["moves"]] == [1, 3, 5, 7]
    mate = analysis["moves"][-1]
    assert mate["san_move"] == "Qxf7#"
    assert (mate["eval_before_mate"], mate["eval_after_mate"]) == (1, 0)
    assert mate["eval_after_cp"] is None
    assert analysis["moves"][0]["clock_after_ms"] == 598_000


def test_reuses_active_and_completed_jobs_unless_forced(client, db, imported, settings):
    _, games = imported
    first = client.post(f"{API}/games/{games[0]}/analyze").json()
    again = client.post(f"{API}/games/{games[0]}/analyze")
    assert again.status_code == 200 and again.json()["id"] == first["id"]

    run_once(db, FakeAnalyzer(), settings, "w")
    completed = client.post(f"{API}/games/{games[0]}/analyze")
    assert completed.status_code == 200 and completed.json()["id"] == first["id"]

    forced = client.post(f"{API}/games/{games[0]}/analyze", json={"force": True})
    assert forced.status_code == 202 and forced.json()["id"] != first["id"]


def test_unresolved_mapping_cannot_be_analyzed(client, imported):
    _, games = imported
    resp = client.post(f"{API}/games/{games[4]}/analyze")  # ambiguous game
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["mapping_status"] == "ambiguous"


def test_critical_pass_is_queued_and_reanalyzes_only_critical_plies(client, db, settings):
    student = client.post(
        f"{API}/students", json={"display_name": "S", "aliases": ["Ovindu"]}
    ).json()
    report = _upload(client, student["id"], MISSED_MATE_PGN, "m.pgn")
    game_id = report["games"][0]["game_id"]
    client.post(f"{API}/games/{game_id}/analyze")

    run_once(db, FakeAnalyzer(), settings, "w")  # baseline
    critical = db.scalars(
        select(AnalysisRun).where(AnalysisRun.pass_type == AnalysisPass.CRITICAL)
    ).one()
    assert critical.status == JobStatus.QUEUED
    assert critical.configuration["plies"] == [7]
    assert critical.configuration["depth"] == 12

    run_once(db, FakeAnalyzer(), settings, "w")  # critical pass
    analysis = client.get(f"{API}/games/{game_id}/analysis").json()
    assert analysis["critical"]["status"] == "completed"
    assert [m["ply"] for m in analysis["critical_moves"]] == [7]
    missed = analysis["critical_moves"][0]
    assert missed["features"]["mate_transition"] == "missed_mate"
    assert missed["best_move_loss_cp"] is None
    assert missed["best_move_uci"] == "h5f7"
    assert run_once(db, FakeAnalyzer(), settings, "w") is False  # no further passes


def test_failure_is_retried_without_duplicate_rows(client, db, imported, settings):
    _, games = imported
    job_id = uuid.UUID(client.post(f"{API}/games/{games[0]}/analyze").json()["id"])

    run_once(db, FakeAnalyzer(fail_times=3), settings, "w")
    run = db.get(AnalysisRun, job_id)
    db.refresh(run)
    assert run.status == JobStatus.QUEUED
    assert run.attempts == 1
    assert "simulated engine failure" in run.error_message

    run_once(db, FakeAnalyzer(), settings, "w")
    db.refresh(run)
    assert run.status == JobStatus.COMPLETED
    assert run.error_message is None
    count = db.scalar(
        select(func.count()).select_from(MoveAnalysis).where(MoveAnalysis.analysis_run_id == job_id)
    )
    assert count == 4


def test_gives_up_after_max_attempts(client, db, imported, settings):
    _, games = imported
    job_id = uuid.UUID(client.post(f"{API}/games/{games[0]}/analyze").json()["id"])
    broken = FakeAnalyzer(fail_always=True)
    for _ in range(settings.analysis_max_attempts):
        run_once(db, broken, settings, "w")
    run = db.get(AnalysisRun, job_id)
    db.refresh(run)
    assert run.status == JobStatus.FAILED
    assert run.attempts == settings.analysis_max_attempts
    assert run_once(db, broken, settings, "w") is False


def test_stale_running_job_is_reclaimed(client, db, imported, settings):
    _, games = imported
    job_id = uuid.UUID(client.post(f"{API}/games/{games[0]}/analyze").json()["id"])
    run = db.get(AnalysisRun, job_id)
    run.status = JobStatus.RUNNING
    run.attempts = 1
    run.claimed_by = "crashed-worker"
    run.started_at = utcnow() - timedelta(hours=2)
    db.commit()

    claimed = claim_next_run(db, settings, "new-worker")
    assert claimed is not None and claimed.id == job_id
    assert claimed.claimed_by == "new-worker"
    assert claimed.attempts == 2


def test_fresh_running_job_is_not_stolen(client, db, imported, settings):
    _, games = imported
    client.post(f"{API}/games/{games[0]}/analyze")
    assert claim_next_run(db, settings, "w1") is not None
    assert claim_next_run(db, settings, "w2") is None


def test_other_coach_cannot_queue_or_read(client, db, imported, make_user, settings):
    _, games = imported
    job = client.post(f"{API}/games/{games[0]}/analyze").json()
    run_once(db, FakeAnalyzer(), settings, "w")
    make_user("other@example.com")
    other = {"X-Dev-User-Email": "other@example.com"}
    assert client.post(f"{API}/games/{games[0]}/analyze", headers=other).status_code == 403
    assert client.get(f"{API}/analysis-jobs/{job['id']}", headers=other).status_code == 403
    assert client.get(f"{API}/games/{games[0]}/analysis", headers=other).status_code == 403
