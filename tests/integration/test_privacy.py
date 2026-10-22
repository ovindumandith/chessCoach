"""Student deletion removes all derived data, keeps other students' data intact."""

import uuid

from sqlalchemy import func, select

from chesscoach.analysis.worker import run_once
from chesscoach.core.config import Settings
from chesscoach.db import models as m
from tests.fakes import FakeAnalyzer
from tests.integration.test_profiles import PGN

API = "/api/v1"


def count(db, model, **where):
    q = select(func.count()).select_from(model)
    for k, v in where.items():
        q = q.where(getattr(model, k) == v)
    return db.scalar(q)


def setup_student(client, db, name, aliases, data=PGN):
    s = client.post(f"{API}/students", json={"display_name": name, "aliases": aliases}).json()
    report = client.post(
        f"{API}/students/{s['id']}/games/import",
        headers=client.as_student(s["id"]),
        files={"file": ("g.pgn", data, "application/x-chess-pgn")},
    ).json()
    for g in report["games"]:
        if g["game_id"] and g["status"] == "imported":
            client.post(
                f"{API}/games/{g['game_id']}/analyze", headers=client.as_student.game(g["game_id"])
            )
    while run_once(db, FakeAnalyzer(), Settings(stockfish_depth=8), "w"):
        pass
    return s


def test_delete_student_removes_everything_derived(client, db, storage_dir, make_user):
    victim = setup_student(client, db, "To Delete", ["Ovindu"])
    # Same file imported for another student who appears as Black in those games.
    keeper = setup_student(client, db, "Keeper", ["Opp1", "Opp2", "Opp3"])
    vid, kid = uuid.UUID(victim["id"]), uuid.UUID(keeper["id"])

    # Exercises, attempts and a lesson from the victim's own login (the one that added the games).
    victim_h = client.as_student(victim["id"])
    learner = db.scalar(select(m.User).where(m.User.email == victim_h["X-Dev-User-Email"]))
    learner.password_hash = "scrypt$x"
    db.commit()
    ex = client.post(f"{API}/students/{victim['id']}/exercises", headers=victim_h).json()[0]
    client.post(f"{API}/exercises/{ex['id']}/attempts", json={"move": "Qxf7#"}, headers=victim_h)
    client.post(f"{API}/students/{victim['id']}/coaching/lessons", headers=victim_h)
    first = client.get(f"{API}/students/{victim['id']}/mistakes", headers=victim_h).json()
    g = next(g for g in first["games"] if g["mistakes"])
    ack = f"{API}/games/{g['game_id']}/mistakes/{g['mistakes'][0]['ply']}/acknowledgement"
    assert client.put(ack, headers=victim_h).status_code == 200
    db.add(  # a stored improvement plan (needs 5 games through the API; stored directly here)
        m.ImprovementPlan(
            student_id=vid,
            model_provider="template",
            model_id="plan-template-v1",
            prompt_version="improvement_plan_v1",
            context_hash="x" * 64,
            games_included=3,
            games_total=3,
            validation_status=m.ValidationStatus.FALLBACK,
        )
    )
    db.commit()
    assert count(db, m.WeaknessObservation, student_id=vid) > 0
    assert count(db, m.ProfileSnapshot, student_id=vid) > 0
    keeper_games_before = count(db, m.Game, student_id=kid)
    files_before = list(storage_dir.rglob("*.pgn"))

    wrong = client.delete(f"{API}/students/{victim['id']}", params={"confirm": "to delete"})
    assert wrong.status_code == 422  # must match the exact name
    resp = client.delete(f"{API}/students/{victim['id']}", params={"confirm": "To Delete"})
    assert resp.status_code == 200
    deleted = resp.json()["deleted"]
    assert deleted["games"] == 3 and deleted["exercises"] >= 1 and deleted["coaching_sessions"] == 1
    assert deleted["mistake_acknowledgements"] == 1
    assert deleted["improvement_plans"] == 1
    assert count(db, m.ImprovementPlan, student_id=vid) == 0
    assert count(db, m.MistakeAcknowledgement, student_id=vid) == 0
    assert deleted["student_logins_anonymised"] == 1

    db.expire_all()
    assert db.get(m.Student, vid) is None
    for model in (
        m.Game,
        m.WeaknessObservation,
        m.SkillOpportunity,
        m.ProfileSnapshot,
        m.StudentSkillProfile,
        m.Exercise,
        m.ExerciseAttempt,
        m.CoachingSession,
        m.StudentAccess,
        m.StudentAlias,
    ):
        assert count(db, model, student_id=vid) == 0, model.__name__
    victim_runs = db.scalar(
        select(func.count())
        .select_from(m.AnalysisRun)
        .where(m.AnalysisRun.game_id.not_in(select(m.Game.id)))
    )
    assert victim_runs == 0  # no orphaned analysis

    # The other student's data and the shared PGN file survive.
    assert count(db, m.Game, student_id=kid) == keeper_games_before
    assert list(storage_dir.rglob("*.pgn")) == files_before

    # The login is anonymised, deactivated and unusable; the audit trail holds no name.
    user = db.get(m.User, learner.id)
    assert user.is_active is False and user.password_hash is None
    assert user.email.endswith("@deleted.invalid")
    event = db.scalar(select(m.AuditEvent).where(m.AuditEvent.action == "student.delete"))
    assert event.entity_id == str(vid) and "To Delete" not in str(event.details)


def test_last_user_of_a_file_removes_the_stored_pgn(client, db, storage_dir):
    s = setup_student(client, db, "Solo", ["Ovindu"])
    assert list(storage_dir.rglob("*.pgn"))
    client.delete(f"{API}/students/{s['id']}", params={"confirm": "Solo"})
    assert list(storage_dir.rglob("*.pgn")) == []
    assert count(db, m.SourceFile) == 0


def test_only_the_coach_may_delete(client, db, make_user):
    s = client.post(f"{API}/students", json={"display_name": "Mine"}).json()
    make_user("other@example.com")
    resp = client.delete(
        f"{API}/students/{s['id']}",
        params={"confirm": "Mine"},
        headers={"X-Dev-User-Email": "other@example.com"},
    )
    assert resp.status_code == 403
