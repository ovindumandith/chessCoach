"""Analysis -> automatic classification -> coach review -> reclassification."""

import uuid

import pytest
from sqlalchemy import select

from chesscoach.analysis.worker import run_once
from chesscoach.core.config import Settings
from chesscoach.db.enums import AccessLevel, OpportunityOutcome, UserRole
from chesscoach.db.models import AuditEvent, SkillOpportunity, StudentAccess
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
    return Settings(stockfish_depth=8, stockfish_critical_depth=12, analysis_multipv=2)


@pytest.fixture
def classified(client, db, settings):
    student = client.post(
        f"{API}/students", json={"display_name": "S", "aliases": ["Ovindu"]}
    ).json()
    report = client.post(
        f"{API}/students/{student['id']}/games/import",
        files={"file": ("m.pgn", MISSED_MATE_PGN, "application/x-chess-pgn")},
    ).json()
    game_id = report["games"][0]["game_id"]
    client.post(f"{API}/games/{game_id}/analyze")
    run_once(db, FakeAnalyzer(), settings, "w")  # baseline: critical pass queued, no classify
    assert client.get(f"{API}/students/{student['id']}/weaknesses").json()["total"] == 0
    run_once(db, FakeAnalyzer(), settings, "w")  # critical pass, then automatic classification
    return student, game_id


def _weaknesses(client, student_id, **params):
    return client.get(f"{API}/students/{student_id}/weaknesses", params=params).json()


def test_missed_mate_classified_with_evidence(client, db, classified):
    student, game_id = classified
    page = _weaknesses(client, student["id"], evidence_type="motif")
    mate = next(w for w in page["items"] if w["subskill_code"] == "mating_patterns")
    assert mate["skill_code"] == "tactical_awareness"
    assert mate["review_status"] == "candidate"
    assert mate["details"]["motif_kind"] == "missed"
    assert mate["details"]["ply"] == 7
    assert mate["classifier_version"] == "classifier-v1"
    assert mate["taxonomy_version"] == "taxonomy-v1"
    assert "not a calibrated probability" in mate["confidence_note"]
    ev = mate["evidence"]
    assert ev["san_move"] == "Qe2"
    assert ev["best_line_san"][0] == "Qxf7#"
    assert ev["eval_before_mate"] == 1

    opp = db.scalars(select(SkillOpportunity)).all()
    assert [(o.subskill_code, o.outcome) for o in opp] == [
        ("mating_patterns", OpportunityOutcome.MISSED)
    ]


def test_taxonomy_endpoint(client):
    tax = client.get(f"{API}/taxonomy").json()
    assert tax["version"] == "taxonomy-v1"
    assert "forks" in tax["categories"]["tactical_awareness"]["subskills"]


def test_review_confirm_reject_correct(client, db, classified):
    student, _ = classified
    items = _weaknesses(client, student["id"])["items"]
    assert len(items) >= 2
    mate = next(w for w in items if w["subskill_code"] == "mating_patterns")
    other = next(w for w in items if w["id"] != mate["id"])

    confirmed = client.patch(
        f"{API}/observations/{mate['id']}/review",
        json={"action": "confirm", "note": "Classic Qxf7# pattern"},
    ).json()
    assert confirmed["review_status"] == "confirmed"
    assert confirmed["review_note"] == "Classic Qxf7# pattern"
    assert confirmed["reviewed_at"] is not None

    bad = client.patch(
        f"{API}/observations/{other['id']}/review",
        json={"action": "correct", "skill_code": "not_a_skill"},
    )
    assert bad.status_code == 422
    missing = client.patch(f"{API}/observations/{other['id']}/review", json={"action": "correct"})
    assert missing.status_code == 422

    corrected = client.patch(
        f"{API}/observations/{other['id']}/review",
        json={
            "action": "correct",
            "skill_code": "opening_knowledge",
            "subskill_code": "opening_traps",
        },
    ).json()
    assert corrected["review_status"] == "corrected"
    assert corrected["skill_code"] == "opening_knowledge"
    assert corrected["details"]["original"]["skill_code"] == other["skill_code"]

    actions = set(db.scalars(select(AuditEvent.action)).all())
    assert {"observation.confirm", "observation.correct"} <= actions


def test_reclassify_preserves_reviews_without_duplicates(client, classified):
    student, game_id = classified
    before = _weaknesses(client, student["id"])["items"]
    target = before[0]
    client.patch(f"{API}/observations/{target['id']}/review", json={"action": "confirm"})
    corrected_target = before[1]
    client.patch(
        f"{API}/observations/{corrected_target['id']}/review",
        json={
            "action": "correct",
            "skill_code": "calculation",
            "subskill_code": "forcing_variations",
        },
    )

    for _ in range(2):  # idempotent
        result = client.post(f"{API}/games/{game_id}/classify").json()
        assert result["preserved_reviewed"] == 2

    after = _weaknesses(client, student["id"])["items"]
    assert len(after) == len(before)
    by_id = {w["id"]: w for w in after}
    assert by_id[target["id"]]["review_status"] == "confirmed"
    assert by_id[corrected_target["id"]]["skill_code"] == "calculation"
    # The corrected finding's original label is not regenerated as a new candidate.
    original = (corrected_target["skill_code"], corrected_target["subskill_code"])
    assert not any(
        (w["skill_code"], w["subskill_code"]) == original and w["review_status"] == "candidate"
        for w in after
    )


def test_student_never_sees_rejected_findings(client, db, classified, make_user):
    student, _ = classified
    items = _weaknesses(client, student["id"])["items"]
    client.patch(f"{API}/observations/{items[0]['id']}/review", json={"action": "reject"})

    learner = make_user("learner@example.com", UserRole.STUDENT)
    db.add(
        StudentAccess(
            user_id=learner.id, student_id=uuid.UUID(student["id"]), access_level=AccessLevel.SELF
        )
    )
    db.commit()
    me = {"X-Dev-User-Email": "learner@example.com"}
    seen = client.get(f"{API}/students/{student['id']}/weaknesses", headers=me).json()
    assert seen["total"] == len(items) - 1
    assert all(w["review_status"] != "rejected" for w in seen["items"])
    # Students cannot review or reclassify.
    assert (
        client.patch(
            f"{API}/observations/{items[1]['id']}/review", json={"action": "confirm"}, headers=me
        ).status_code
        == 403
    )


def test_other_coach_denied(client, classified, make_user):
    student, game_id = classified
    items = _weaknesses(client, student["id"])["items"]
    make_user("other@example.com")
    other = {"X-Dev-User-Email": "other@example.com"}
    assert (
        client.get(f"{API}/students/{student['id']}/weaknesses", headers=other).status_code == 403
    )
    assert client.post(f"{API}/games/{game_id}/classify", headers=other).status_code == 403
    assert (
        client.patch(
            f"{API}/observations/{items[0]['id']}/review", json={"action": "confirm"}, headers=other
        ).status_code
        == 403
    )


def test_classify_without_analysis_is_conflict(client, mixed_pgn):
    student = client.post(
        f"{API}/students", json={"display_name": "S", "aliases": ["Ovindu"]}
    ).json()
    report = client.post(
        f"{API}/students/{student['id']}/games/import",
        files={"file": ("g.pgn", mixed_pgn, "application/x-chess-pgn")},
    ).json()
    game_id = report["games"][0]["game_id"]
    assert client.post(f"{API}/games/{game_id}/classify").status_code == 409
