"""Profile -> evidence retrieval -> (mock) LLM -> validation -> lesson or fallback."""

import uuid

import pytest

from chesscoach.analysis.worker import run_once
from chesscoach.coaching.providers import LLMError, MockProvider
from chesscoach.core.config import Settings
from chesscoach.db.enums import AccessLevel, UserRole
from chesscoach.db.models import StudentAccess
from tests.fakes import FakeAnalyzer
from tests.integration.test_profiles import PGN

API = "/api/v1"


@pytest.fixture
def student(client, db):
    s = client.post(
        f"{API}/students", json={"display_name": "S", "aliases": ["Ovindu"], "skill_level": "club"}
    ).json()
    report = client.post(
        f"{API}/students/{s['id']}/games/import",
        files={"file": ("g.pgn", PGN, "application/x-chess-pgn")},
    ).json()
    for g in report["games"]:
        client.post(f"{API}/games/{g['game_id']}/analyze")
    while run_once(db, FakeAnalyzer(), Settings(stockfish_depth=8), "w"):
        pass
    return s


def grounded(payload: dict) -> dict:
    """A response that uses only supplied evidence."""
    ctx = payload["context"]
    p = ctx["positions"][0]
    return {
        "objective": "Look for forcing moves before anything else.",
        "skill_code": ctx["objective"]["skill_code"],
        "recurring_pattern": f"In several games you played {p['played_move_san']} "
        f"when {p['eval_before']} was available.",
        "examples": [
            {
                "game_id": p["game_id"],
                "ply": p["ply"],
                "fen": p["fen"],
                "engine_best_move_uci": p["engine_best_move_uci"],
                "explanation": f"The evaluation went from {p['eval_before']} to {p['eval_after']}.",
            }
        ],
        "student_question": "List every check White has here. Which one ends the game?",
        "exercise_recommendation": "Twenty mate-in-one puzzles.",
        "follow_up_metric": "18 of 20 on unseen puzzles.",
        "uncertainty": "Findings are unreviewed.",
        "verified_facts": ["The mate was available."],
        "hypotheses": ["Scanning checks first may help."],
    }


def use(monkeypatch, provider):
    monkeypatch.setattr("chesscoach.coaching.service.get_provider", lambda settings: provider)
    return provider


def lesson(client, sid, **kw):
    return client.post(f"{API}/students/{sid}/coaching/lessons", **kw)


def test_disabled_llm_returns_validated_template(client, student):
    resp = lesson(client, student["id"])
    assert resp.status_code == 201
    body = resp.json()
    assert body["used_fallback"] is True
    assert body["session"]["model_provider"] == "template"
    assert body["session"]["validation_status"] == "fallback"
    assert body["lesson"]["skill_code"] == "tactical_awareness"
    assert body["lesson"]["examples"][0]["fen"]
    assert body["session"]["evidence_references"]


def test_grounded_llm_lesson_is_accepted(client, student, monkeypatch):
    provider = use(monkeypatch, MockProvider(grounded))
    body = lesson(client, student["id"]).json()
    assert body["used_fallback"] is False
    session = body["session"]
    assert session["model_provider"] == "mock"
    assert session["validation_status"] == "valid"
    assert session["prompt_version"] == "chess_coach_v1"
    assert session["token_usage"]["output_tokens"] == 200

    ctx = provider.calls[0]["context"]
    assert ctx["objective"]["subskill_code"] == "mating_patterns"
    assert ctx["student_level"] == "club"
    assert 1 <= len(ctx["positions"]) <= 5
    assert len({p["game_id"] for p in ctx["positions"]}) == len(ctx["positions"])
    pos = ctx["positions"][0]
    assert pos["played_move_san"] == "Qe2" and pos["eval_before"] == "mate in 1"


def test_rejected_attempt_is_retried_with_feedback(client, student, monkeypatch):
    def responder(payload):
        data = grounded(payload)
        if "previous_attempt_rejected_because" not in payload:
            data["recurring_pattern"] = "You keep missing Nxe5 tricks."  # invented move
        return data

    provider = use(monkeypatch, MockProvider(responder))
    body = lesson(client, student["id"]).json()
    assert body["used_fallback"] is False
    assert len(provider.calls) == 2
    assert any("Nxe5" in e for e in provider.calls[1]["previous_attempt_rejected_because"])
    assert any("Nxe5" in e for e in body["session"]["validation_errors"])


def test_persistently_invalid_llm_falls_back(client, student, monkeypatch):
    def responder(payload):
        data = grounded(payload)
        data["examples"][0]["fen"] = "8/8/8/8/8/8/8/K6k w - - 0 1"  # fabricated position
        return data

    use(monkeypatch, MockProvider(responder))
    body = lesson(client, student["id"]).json()
    assert body["used_fallback"] is True
    assert any("FEN" in e for e in body["session"]["validation_errors"])
    attempts = len(body["session"]["validation_errors"])
    assert attempts >= 2  # both attempts rejected


def test_schema_violations_fall_back(client, student, monkeypatch):
    use(monkeypatch, MockProvider(lambda payload: {"objective": "only this"}))
    body = lesson(client, student["id"]).json()
    assert body["used_fallback"] is True
    assert any(e.startswith("schema:") for e in body["session"]["validation_errors"])


def test_provider_failure_falls_back(client, student, monkeypatch):
    use(monkeypatch, MockProvider(lambda payload: LLMError("connection error: boom")))
    body = lesson(client, student["id"]).json()
    assert body["used_fallback"] is True
    assert body["session"]["validation_errors"] == ["connection error: boom"]


def test_previous_lessons_feed_the_next_context(client, student, monkeypatch):
    lesson(client, student["id"])
    provider = use(monkeypatch, MockProvider(grounded))
    lesson(client, student["id"])
    previous = provider.calls[0]["context"]["previous_lessons"]
    assert previous and previous[0]["skill_code"] == "tactical_awareness"
    history = client.get(f"{API}/students/{student['id']}/coaching/sessions").json()
    assert history["total"] == 2


def test_requested_skill_without_evidence_is_conflict(client, student):
    resp = lesson(
        client,
        student["id"],
        json={"skill_code": "endgame_technique", "subskill_code": "rook_endgames"},
    )
    assert resp.status_code == 409


def test_no_profile_is_conflict(client):
    s = client.post(f"{API}/students", json={"display_name": "New"}).json()
    assert lesson(client, s["id"]).status_code == 409


def test_access_rules(client, db, student, make_user):
    make_user("other@example.com")
    assert (
        lesson(client, student["id"], headers={"X-Dev-User-Email": "other@example.com"}).status_code
        == 403
    )
    learner = make_user("learner@example.com", UserRole.STUDENT)
    db.add(
        StudentAccess(
            user_id=learner.id, student_id=uuid.UUID(student["id"]), access_level=AccessLevel.SELF
        )
    )
    db.commit()
    me = {"X-Dev-User-Email": "learner@example.com"}
    assert lesson(client, student["id"], headers=me).status_code == 201  # students may ask


def test_unexplained_errors_are_never_the_objective(client, db, student):
    from sqlalchemy import select

    from chesscoach.db.models import StudentSkillProfile

    # Simulate a snapshot built before unclassified was excluded from ranking.
    for row in db.scalars(select(StudentSkillProfile)).all():
        if row.skill_code == "unclassified":
            row.priority_score, row.error_count = 99.0, 5
    db.commit()
    body = lesson(client, student["id"]).json()
    assert body["lesson"]["skill_code"] == "tactical_awareness"
    assert lesson(client, student["id"], json={"skill_code": "unclassified"}).status_code == 409
