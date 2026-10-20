"""Exercise selection from analyzed games, hidden solutions, attempts, progress."""

import json
import uuid

import pytest

from chesscoach.analysis.worker import run_once
from chesscoach.coaching.providers import MockProvider
from chesscoach.core.config import Settings
from chesscoach.db.enums import AccessLevel, UserRole
from chesscoach.db.models import StudentAccess
from tests.fakes import FakeAnalyzer
from tests.integration.test_coaching import grounded
from tests.integration.test_profiles import PGN

API = "/api/v1"
ME = {"X-Dev-User-Email": "learner@example.com"}


@pytest.fixture
def student(client, db, make_user):
    s = client.post(f"{API}/students", json={"display_name": "S", "aliases": ["Ovindu"]}).json()
    report = client.post(
        f"{API}/students/{s['id']}/games/import",
        files={"file": ("g.pgn", PGN, "application/x-chess-pgn")},
    ).json()
    for g in report["games"]:
        client.post(f"{API}/games/{g['game_id']}/analyze")
    while run_once(db, FakeAnalyzer(), Settings(stockfish_depth=8), "w"):
        pass
    learner = make_user("learner@example.com", UserRole.STUDENT)
    db.add(
        StudentAccess(
            user_id=learner.id, student_id=uuid.UUID(s["id"]), access_level=AccessLevel.SELF
        )
    )
    db.commit()
    return s


def create(client, sid, **body):
    return client.post(f"{API}/students/{sid}/exercises", json=body or None)


def test_review_exercises_from_own_mistakes_with_hidden_solutions(client, student):
    resp = create(client, student["id"])  # coach creates; defaults to top skill
    assert resp.status_code == 201
    exercises = resp.json()
    assert len(exercises) == 3  # the missed mate in each of the three games
    ex = exercises[0]
    assert ex["skill_code"] == "tactical_awareness" and ex["subskill_code"] == "mating_patterns"
    assert ex["purpose"] == "review" and ex["status"] == "open"
    assert ex["side_to_move"] == "white" and ex["prompt"] == "White to move. Find the best move."
    assert ex["solution"] is None and ex["hints_available"] == 3
    assert "h5f7" not in resp.text and "Qxf7" not in resp.text  # solution never leaks


def test_hints_attempts_and_solve(client, student):
    ex = create(client, student["id"]).json()[0]
    url = f"{API}/exercises/{ex['id']}"

    hints = [client.post(f"{url}/hint", headers=ME).json() for _ in range(3)]
    assert hints[0]["hint"] == "There is a forced checkmate."
    assert hints[2]["hint"] == "The queen on h5." and hints[2]["hints_remaining"] == 0
    assert client.post(f"{url}/hint", headers=ME).status_code == 409

    illegal = client.post(f"{url}/attempts", json={"move": "Ke3"}, headers=ME)
    assert illegal.status_code == 422
    assert client.get(url, headers=ME).json()["attempts"] == []  # not recorded

    wrong = client.post(f"{url}/attempts", json={"move": "h5e2"}, headers=ME).json()
    assert wrong["correct"] is False and wrong["attempts_left"] == 2
    assert wrong["exercise"]["solution"] is None

    right = client.post(
        f"{url}/attempts", json={"move": "Qxf7#", "time_taken_ms": 4200}, headers=ME
    ).json()
    assert right["correct"] is True
    done = right["exercise"]
    assert done["status"] == "solved"
    assert done["solution"]["accepted_moves_san"] == ["Qxf7#"]
    assert done["solution"]["game_move"]["san"] == "Qe2"
    assert [(a["move_san"], a["is_correct"], a["hints_used"]) for a in done["attempts"]] == [
        ("Qe2", False, 3),
        ("Qxf7#", True, 3),
    ]
    assert client.post(f"{url}/attempts", json={"move": "Qxf7#"}, headers=ME).status_code == 409


def test_failure_after_max_attempts_and_reveal(client, student):
    first, second, _ = create(client, student["id"]).json()
    for _ in range(3):
        last = client.post(
            f"{API}/exercises/{first['id']}/attempts", json={"move": "a2a3"}, headers=ME
        ).json()
    assert last["exercise"]["status"] == "failed" and last["exercise"]["solution"]

    revealed = client.post(f"{API}/exercises/{second['id']}/reveal", headers=ME).json()
    assert revealed["status"] == "revealed"
    assert revealed["solution"]["accepted_moves_uci"] == ["h5f7"]


def test_only_the_student_can_answer(client, student, make_user):
    ex = create(client, student["id"]).json()[0]
    coach = client.post(f"{API}/exercises/{ex['id']}/attempts", json={"move": "Qxf7#"})
    assert coach.status_code == 403
    make_user("other@example.com")
    other = {"X-Dev-User-Email": "other@example.com"}
    assert client.get(f"{API}/exercises/{ex['id']}", headers=other).status_code == 403
    assert create(client, student["id"]).status_code == 409  # all three positions used
    # The student may request their own exercises too (none left here).
    assert client.post(f"{API}/students/{student['id']}/exercises", headers=ME).status_code == 409


def test_skills_without_board_exercises(client, student):
    assert (
        create(
            client, student["id"], skill_code="practical_play", subskill_code="time_management"
        ).status_code
        == 409
    )
    assert create(client, student["id"], skill_code="unclassified").status_code == 409
    assert (
        create(
            client, student["id"], skill_code="endgame_technique", subskill_code="rook_endgames"
        ).status_code
        == 409
    )  # no such positions


def test_progress_profile_and_coaching_see_results(client, student, monkeypatch):
    sid = student["id"]
    a, b, c = create(client, sid).json()
    client.post(f"{API}/exercises/{a['id']}/attempts", json={"move": "Qxf7#"}, headers=ME)
    client.post(f"{API}/exercises/{b['id']}/attempts", json={"move": "a2a3"}, headers=ME)
    client.post(f"{API}/exercises/{b['id']}/attempts", json={"move": "Qxf7#"}, headers=ME)

    prog = client.get(f"{API}/students/{sid}/progress").json()
    mate = next(s for s in prog["skills"] if s["subskill_code"] == "mating_patterns")
    stats = mate["exercises"]
    assert (stats["assigned"], stats["attempted"], stats["solved_first_try"]) == (3, 2, 1)
    assert stats["first_try_accuracy"] == 0.5 and stats["solved"] == 2
    assert mate["profile_trend"]

    before = client.get(f"{API}/students/{sid}/profile").json()
    assert before["stale"] is True  # attempts are new evidence for the profile view
    rebuilt = client.post(f"{API}/students/{sid}/profile/rebuild").json()
    after = next(s for s in rebuilt["skills"] if s["subskill_code"] == "mating_patterns")
    old = next(s for s in before["skills"] if s["subskill_code"] == "mating_patterns")
    assert after["evidence_summary"]["exercises"]["attempted"] == 2
    assert after["evidence_summary"]["exercises"]["affects_priority"] is False
    assert after["priority_score"] == old["priority_score"]  # exercises never move priority
    assert after["state"] == old["state"]

    provider = MockProvider(grounded)
    monkeypatch.setattr("chesscoach.coaching.service.get_provider", lambda s: provider)
    client.post(f"{API}/students/{sid}/coaching/lessons")
    history = provider.calls[0]["context"]["exercise_history"]
    assert {h["status"] for h in history} == {"solved"}
    assert sorted(h["first_try_correct"] for h in history) == [False, True]
    assert "h5f7" not in json.dumps(history)  # outcomes only, no solutions
