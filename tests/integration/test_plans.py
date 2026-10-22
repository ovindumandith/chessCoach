"""The "Chess LLM" improvement plan: eligibility, context, validation, fallback, history."""

import pytest

from chesscoach.analysis.worker import run_once
from chesscoach.coaching.providers import LLMError, MockProvider
from chesscoach.core.config import Settings
from tests.fakes import FakeAnalyzer
from tests.integration.test_recurring_mistakes import FOUND, MISSED, game

API = "/api/v1"


def setup(client, db, n_games):
    pgn = "".join(
        game(i, f"2024.0{i}.10", "Me", f"Opp{i}", FOUND if i == 2 else MISSED)
        for i in range(1, n_games + 1)
    ).encode()
    s = client.post(f"{API}/students", json={"display_name": "S", "aliases": ["Me"]}).json()
    report = client.post(
        f"{API}/students/{s['id']}/games/import",
        headers=client.as_student(s["id"]),
        files={"file": ("g.pgn", pgn, "application/x-chess-pgn")},
    ).json()
    for g in report["games"]:
        client.post(f"{API}/games/{g['game_id']}/analyze", headers=client.as_student(s["id"]))
    while run_once(db, FakeAnalyzer(), Settings(stockfish_depth=8), "w"):
        pass
    return s


@pytest.fixture
def five(client, db):
    return setup(client, db, 5)


def use(monkeypatch, provider):
    monkeypatch.setattr("chesscoach.coaching.plan.plan_provider", lambda settings: provider)
    return provider


def mate_mistake(ctx):
    return next(
        m
        for g in ctx["games"]
        for m in g["mistakes"]
        if any(k["subskill_code"] == "mating_patterns" for k in m["kinds"])
    )


def good(payload, *, explanation=None, game_id=None, theme="mateIn1"):
    ctx = payload["context"]
    m = mate_mistake(ctx)
    return {
        "title": "Your plan: stop missing mates",
        "summary": f"You missed {m['better_move']} more than once.",
        "strengths": ["You develop quickly in the opening."],
        "weaknesses": [
            {
                "skill_code": "tactical_awareness",
                "subskill_code": "mating_patterns",
                "title": "Missing mate in one",
                "explanation": explanation
                or f"On move {m['move_number']} you played {m['move']}; {m['better_move']} mated.",
                "evidence": [{"game_id": game_id or m["game_id"], "ply": m["ply"]}],
            }
        ],
        "plan": [
            {
                "period": "Weeks 1-2",
                "focus": "Mating patterns",
                "activities": ["Solve 20 mate-in-one puzzles a day."],
                "goal": "90% first-try accuracy.",
            },
            {
                "period": "Weeks 3-4",
                "focus": "Checking every check",
                "activities": ["Before each move, list every check."],
                "goal": "No missed mate in five games.",
            },
        ],
        "training_routine": ["15 minutes of puzzles daily."],
        "puzzle_themes": [theme],
        "study_topics": ["Basic mating patterns"],
        "habits": ["Checks, captures, threats."],
        "milestones": ["Mate-in-one puzzle rating up 100."],
        "uncertainty": "Only five games so far.",
    }


def plans_url(sid):
    return f"{API}/students/{sid}/improvement-plans"


def test_needs_five_analyzed_games(client, db):
    s = setup(client, db, 4)
    me = client.as_student(s["id"])
    overview = client.get(plans_url(s["id"]), headers=me).json()
    assert overview["analyzed_games"] == 4 and overview["required_games"] == 5
    assert overview["eligible"] is False and overview["plans"] == []
    resp = client.post(plans_url(s["id"]), headers=me)
    assert resp.status_code == 409 and "At least 5 analyzed games" in resp.text


def test_llm_plan_from_all_games_is_checked_and_stored(client, five, monkeypatch):
    provider = use(monkeypatch, MockProvider(good, model="openai/gpt-6.1-sol"))
    me = client.as_student(five["id"])
    resp = client.post(plans_url(five["id"]), headers=me)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["validation_status"] == "valid" and body["model_id"] == "openai/gpt-6.1-sol"
    assert body["games_included"] == body["games_total"] == 5
    assert body["plan"]["weaknesses"][0]["subskill_code"] == "mating_patterns"

    # What was sent: every analyzed game with its moves and the mistakes, engine-grounded.
    sent = provider.calls[0]["context"]
    assert len(sent["games"]) == 5
    assert sent["games"][0]["moves"].startswith("1. e4 e5 2. Bc4")
    m = mate_mistake(sent)
    assert m["move"] == "Qe2" and m["better_move"] == "Qxf7#"
    assert m["eval_before"] == "mate in 1 for you" and m["verdict"] == "blunder"
    assert m["reason"]
    assert {"skill_code": "tactical_awareness", "subskill_code": "mating_patterns"} in sent[
        "allowed"
    ]["skills"]
    assert sent["summary"]["games_analyzed_total"] == 5
    # Stored exactly as sent, for audit and reproducibility.
    stored = client.get(
        f"{API}/improvement-plans/{body['id']}", params={"include_context": True}, headers=me
    ).json()
    assert stored["context"] == sent
    assert stored["prompt_version"] == "improvement_plan_v2"
    # The cited positions come with it, for the mini boards: the board before 4.Qe2.
    pos = stored["positions"][f"{m['game_id']}:{m['ply']}"]
    assert pos["played_san"] == "Qe2" and pos["played_uci"] == "h5e2"
    assert pos["best_san"] == "Qxf7#" and pos["best_uci"] == "h5f7"
    assert pos["fen"].startswith("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/")

    # Every plan is kept; newest first.
    client.post(plans_url(five["id"]), headers=me)
    overview = client.get(plans_url(five["id"]), headers=me).json()
    assert overview["eligible"] and len(overview["plans"]) == 2
    assert overview["plans"][0]["created_at"] >= overview["plans"][1]["created_at"]
    assert "context" not in overview["plans"][0]  # only on request


def test_invented_moves_are_rejected_then_corrected(client, five, monkeypatch):
    def responder(payload):
        if "previous_attempt_rejected_because" in payload:
            return good(payload)
        return good(payload, explanation="You should have played Nd5 and Rxe8 instead.")

    provider = use(monkeypatch, MockProvider(responder))
    body = client.post(plans_url(five["id"]), headers=client.as_student(five["id"])).json()
    assert body["validation_status"] == "valid"
    feedback = provider.calls[1]["previous_attempt_rejected_because"]
    assert any("not in the supplied games or engine lines: Nd5, Rxe8" in f for f in feedback)


def test_unusable_answers_fall_back_to_a_labelled_template(client, five, monkeypatch):
    use(monkeypatch, MockProvider(lambda p: good(p, game_id="not-a-game", theme="madeUp")))
    body = client.post(plans_url(five["id"]), headers=client.as_student(five["id"])).json()
    assert body["validation_status"] == "fallback" and body["model_provider"] == "template"
    assert any("not a supplied mistake" in e for e in body["validation_errors"])
    assert any("unknown puzzle theme madeUp" in e for e in body["validation_errors"])
    plan = body["plan"]
    assert plan["title"] == "Your training plan" and body["model_id"] == "plan-template-v2"
    assert "answer could not be used" in plan["uncertainty"]
    assert plan["weaknesses"] and plan["weaknesses"][0]["evidence"]

    use(monkeypatch, MockProvider(lambda p: LLMError("API error 404: model not found")))
    body = client.post(plans_url(five["id"]), headers=client.as_student(five["id"])).json()
    assert body["validation_status"] == "fallback"
    assert body["validation_errors"] == ["API error 404: model not found"]


def test_without_an_llm_the_template_is_used(client, five):
    body = client.post(plans_url(five["id"]), headers=client.as_student(five["id"])).json()
    assert body["model_provider"] == "template"
    assert "no AI model is configured" in body["plan"]["uncertainty"]


def test_coach_reads_but_does_not_request(client, five, make_user):
    me = client.as_student(five["id"])
    plan = client.post(plans_url(five["id"]), headers=me).json()
    assert client.get(plans_url(five["id"])).status_code == 200  # the coach
    assert client.get(f"{API}/improvement-plans/{plan['id']}").status_code == 200
    assert client.post(plans_url(five["id"])).status_code == 403
    make_user("other-coach@example.com")
    other = {"X-Dev-User-Email": "other-coach@example.com"}
    assert client.get(plans_url(five["id"]), headers=other).status_code == 403
    assert client.get(f"{API}/improvement-plans/{plan['id']}", headers=other).status_code == 403


def test_games_still_in_their_deeper_check_do_not_count(client, five, db):
    """Findings appear only after the deeper check; such a game is pending, not mistake-free."""
    from chesscoach.db.enums import AnalysisPass, JobStatus
    from chesscoach.db.models import AnalysisRun

    run = db.query(AnalysisRun).filter(AnalysisRun.pass_type == AnalysisPass.CRITICAL).first()
    run.status = JobStatus.QUEUED  # this game is back in its deeper check
    db.commit()
    me = client.as_student(five["id"])
    overview = client.get(plans_url(five["id"]), headers=me).json()
    assert overview["analyzed_games"] == 4 and overview["games_in_progress"] == 1
    assert overview["eligible"] is False
    assert client.post(plans_url(five["id"]), headers=me).status_code == 409
    games = client.get(f"{API}/students/{five['id']}/mistakes", headers=me).json()["games"]
    pending = [g for g in games if g["pending"]]
    assert [g["game_id"] for g in pending] == [str(run.game_id)]


def test_dotted_skill_codes_are_accepted_without_a_retry(client, five, monkeypatch):
    """Models sometimes write "skill.subskill" into skill_code; that is fine when valid."""

    def dotted(payload):
        plan = good(payload)
        plan["weaknesses"][0].update(
            skill_code="tactical_awareness.mating_patterns", subskill_code=None
        )
        return plan

    provider = use(monkeypatch, MockProvider(dotted))
    body = client.post(plans_url(five["id"]), headers=client.as_student(five["id"])).json()
    assert body["validation_status"] == "valid" and len(provider.calls) == 1
    w = body["plan"]["weaknesses"][0]
    assert (w["skill_code"], w["subskill_code"]) == ("tactical_awareness", "mating_patterns")
