"""Analysis -> classification -> automatic profile -> review -> versioned rebuild."""

import uuid

import pytest
from sqlalchemy import func, select

from chesscoach.analysis.worker import run_once
from chesscoach.core.config import Settings
from chesscoach.db.enums import AccessLevel, UserRole
from chesscoach.db.models import ProfileSnapshot, StudentAccess
from tests.fakes import FakeAnalyzer

API = "/api/v1"


def game(n: int, date: str, moves: str) -> str:
    return (
        f'[Event "G{n}"]\n[Round "{n}"]\n[Date "{date}"]\n[White "Ovindu"]\n'
        f'[Black "Opp{n}"]\n[Result "*"]\n\n{moves} *\n\n'
    )


# The same missed mate-in-1 (4.Qe2 instead of 4.Qxf7#) in three games on different dates.
MISSED = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qe2"
PGN = (
    game(1, "2024.01.10", MISSED) + game(2, "2024.02.10", MISSED) + game(3, "2024.03.10", MISSED)
).encode()


@pytest.fixture
def settings():
    return Settings(stockfish_depth=8, stockfish_critical_depth=12)


@pytest.fixture
def profiled(client, db, settings):
    student = client.post(
        f"{API}/students", json={"display_name": "S", "aliases": ["Ovindu"]}
    ).json()
    report = client.post(
        f"{API}/students/{student['id']}/games/import",
        files={"file": ("g.pgn", PGN, "application/x-chess-pgn")},
    ).json()
    assert report["imported"] == 3
    for g in report["games"]:
        client.post(f"{API}/games/{g['game_id']}/analyze")
    while run_once(db, FakeAnalyzer(), settings, "w"):
        pass
    return student


def _profile(client, sid, **kw):
    return client.get(f"{API}/students/{sid}/profile", **kw)


def _skill(profile, skill, sub):
    return next(
        s for s in profile["skills"] if s["skill_code"] == skill and s["subskill_code"] == sub
    )


def test_profile_built_automatically_after_analysis(client, db, profiled):
    profile = _profile(client, profiled["id"]).json()
    assert profile["stale"] is False
    snap = profile["snapshot"]
    assert snap["triggered_by"] == "analysis"
    assert snap["summary"]["games_included"] == 3
    assert snap["settings"]["profile_version"] == "profile-v1"
    assert snap["settings"]["classifier_version"] == "classifier-v2"

    mate = _skill(profile, "tactical_awareness", "mating_patterns")
    assert mate["games_affected"] == 3
    assert mate["state"] == "recurring_weakness"
    assert mate["evidence_summary"]["driving_channel"] == "detected"
    assert mate["opportunity_count"] == 3
    assert mate["evidence_summary"]["provisional"] is True  # nothing reviewed yet
    assert len(mate["evidence_summary"]["example_observation_ids"]) == 3
    # The top priority is the recurring missed mate.
    assert profile["skills"][0]["subskill_code"] == "mating_patterns"
    # Worker built incrementally after each game, but only kept changed versions.
    versions = db.scalar(select(func.count()).select_from(ProfileSnapshot))
    assert versions == 3


def test_rebuild_is_idempotent_until_evidence_changes(client, profiled):
    sid = profiled["id"]
    v = _profile(client, sid).json()["snapshot"]["profile_version"]
    same = client.post(f"{API}/students/{sid}/profile/rebuild")
    assert same.status_code == 200
    assert same.json()["snapshot"]["profile_version"] == v

    weaknesses = client.get(
        f"{API}/students/{sid}/weaknesses", params={"skill_code": "tactical_awareness"}
    ).json()["items"]
    for w in weaknesses:
        client.patch(f"{API}/observations/{w['id']}/review", json={"action": "confirm"})
    assert _profile(client, sid).json()["stale"] is True

    new = client.post(f"{API}/students/{sid}/profile/rebuild")
    assert new.status_code == 201
    body = new.json()
    assert body["snapshot"]["profile_version"] == v + 1
    mate = _skill(body, "tactical_awareness", "mating_patterns")
    assert mate["evidence_summary"]["provisional"] is False
    assert mate["evidence_summary"]["change"]["previous_version"] == v
    assert mate["evidence_summary"]["change"]["error_rate_delta"] > 0  # confirmed weighs more

    history = client.get(f"{API}/students/{sid}/profile/history").json()
    assert [h["profile_version"] for h in history["items"]][:2] == [v + 1, v]


def test_cutoff_profile_uses_only_earlier_games(client, profiled):
    sid = profiled["id"]
    resp = client.post(
        f"{API}/students/{sid}/profile/rebuild",
        json={"cutoff_date": "2024.03.01".replace(".", "-")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["snapshot"]["cutoff_date"] == "2024-03-01"
    assert body["snapshot"]["summary"]["games_included"] == 2
    mate = _skill(body, "tactical_awareness", "mating_patterns")
    assert mate["games_affected"] == 2
    assert mate["state"] == "emerging_pattern"
    # The live profile is unaffected by the research snapshot.
    live = _profile(client, sid).json()
    assert live["snapshot"]["cutoff_date"] is None
    assert live["snapshot"]["summary"]["games_included"] == 3


def test_access_rules(client, db, profiled, make_user):
    sid = profiled["id"]
    make_user("other@example.com")
    other = {"X-Dev-User-Email": "other@example.com"}
    assert _profile(client, sid, headers=other).status_code == 403
    assert client.post(f"{API}/students/{sid}/profile/rebuild", headers=other).status_code == 403

    learner = make_user("learner@example.com", UserRole.STUDENT)
    db.add(
        StudentAccess(user_id=learner.id, student_id=uuid.UUID(sid), access_level=AccessLevel.SELF)
    )
    db.commit()
    me = {"X-Dev-User-Email": "learner@example.com"}
    assert _profile(client, sid, headers=me).status_code == 200
    assert client.post(f"{API}/students/{sid}/profile/rebuild", headers=me).status_code == 403


def test_no_profile_yet_is_404(client):
    student = client.post(f"{API}/students", json={"display_name": "New"}).json()
    resp = _profile(client, student["id"])
    assert resp.status_code == 404


def test_skills_ordered_by_priority_with_unranked_last(client, profiled):
    skills = _profile(client, profiled["id"]).json()["skills"]
    priorities = [s["priority_score"] for s in skills]
    ranked = [p for p in priorities if p is not None]
    assert ranked == sorted(ranked, reverse=True)
    first_none = priorities.index(None)
    assert all(p is None for p in priorities[first_none:])  # NULLs last on every database
    assert next(s for s in skills if s["skill_code"] == "unclassified")["priority_score"] is None
