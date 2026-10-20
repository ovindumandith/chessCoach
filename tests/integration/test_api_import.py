"""End-to-end API tests for Phase 1-2: health, students, PGN import, mapping, access control."""

from sqlalchemy import select

from chesscoach.api.deps import DEV_COACH_EMAIL
from chesscoach.db.enums import UserRole
from chesscoach.db.models import AuditEvent

API = "/api/v1"
COACH = {"X-Dev-User-Email": DEV_COACH_EMAIL}  # the development stub's coach


def _create_student(client, name="Ovindu", aliases=("Ovindu", "ovindu_m"), headers=None):
    resp = client.post(
        f"{API}/students", json={"display_name": name, "aliases": list(aliases)}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload(client, student_id, data, filename="games.pgn", headers=None):
    """Upload as the student themself unless other headers are given (coaches can't upload)."""
    return client.post(
        f"{API}/students/{student_id}/games/import",
        files={"file": (filename, data, "application/x-chess-pgn")},
        headers=headers or client.as_student(student_id),
    )


def test_health(client):
    resp = client.get(f"{API}/health")
    assert resp.status_code == 200
    assert resp.json()["database"] == "ok"


def test_create_and_list_students(client):
    student = _create_student(client)
    assert student["aliases"] == ["Ovindu", "ovindu_m"]
    listing = client.get(f"{API}/students").json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == student["id"]


def test_import_multi_game_pgn_report(client, mixed_pgn, storage_dir):
    student = _create_student(client)
    resp = _upload(client, student["id"], mixed_pgn)
    assert resp.status_code == 201, resp.text
    report = resp.json()

    assert report["total_records"] == 5
    assert report["imported"] == 2
    assert report["needs_mapping"] == 2  # unmatched + ambiguous
    assert report["rejected"] == 1
    assert report["duplicates"] == 0

    by_index = {g["index"]: g for g in report["games"]}
    assert by_index[0]["student_color"] == "white"
    assert by_index[1]["student_color"] == "black"
    assert by_index[2]["mapping_status"] == "unmatched"
    assert by_index[3]["status"] == "rejected"
    assert by_index[4]["mapping_status"] == "ambiguous"
    assert by_index[4]["student_color"] is None

    # Source file stored by checksum, never by the uploaded filename.
    stored = list(storage_dir.rglob("*.pgn"))
    assert [p.stem for p in stored] == [report["sha256"]]

    games = client.get(f"{API}/students/{student['id']}/games").json()
    assert games["total"] == 4
    pending = client.get(f"{API}/students/{student['id']}/games?needs_mapping=true").json()
    assert pending["total"] == 2


def test_reimport_is_idempotent(client, mixed_pgn):
    student = _create_student(client)
    _upload(client, student["id"], mixed_pgn)
    second = _upload(client, student["id"], mixed_pgn).json()
    assert second["file_previously_uploaded"] is True
    assert second["duplicates"] == 4
    assert second["imported"] == 0
    assert client.get(f"{API}/students/{student['id']}/games").json()["total"] == 4


def test_same_game_in_different_file_is_duplicate(client, mixed_pgn):
    student = _create_student(client)
    _upload(client, student["id"], mixed_pgn)
    first_game = mixed_pgn.split(b"\n\n[Event")[0] + b"\n"
    report = _upload(client, student["id"], first_game, filename="single.pgn").json()
    assert report["file_previously_uploaded"] is False
    assert report["duplicates"] == 1


def test_game_between_two_students_belongs_to_both(client, mixed_pgn):
    a = _create_student(client, "Ovindu", ["Ovindu"])
    b = _create_student(client, "Opp A", ["Opponent A"])
    ra = _upload(client, a["id"], mixed_pgn).json()
    rb = _upload(client, b["id"], mixed_pgn).json()
    assert ra["games"][0]["student_color"] == "white"
    assert rb["games"][0]["student_color"] == "black"
    assert rb["duplicates"] == 0


def test_confirm_ambiguous_mapping(client, mixed_pgn):
    student = _create_student(client)
    report = _upload(client, student["id"], mixed_pgn).json()
    ambiguous_id = next(g["game_id"] for g in report["games"] if g["index"] == 4)
    resp = client.patch(
        f"{API}/games/{ambiguous_id}/mapping",
        json={"student_color": "black"},
        headers=client.as_student(student["id"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mapping_status"] == "confirmed"
    assert body["student_color"] == "black"
    assert "Nf3" in body["raw_pgn"]


def test_rejects_wrong_extension_and_empty_file(client):
    student = _create_student(client)
    assert _upload(client, student["id"], b"1. e4 *", filename="evil.exe").status_code == 422
    assert _upload(client, student["id"], b"   ").status_code == 422


def test_rejects_oversized_upload(client, monkeypatch):
    from chesscoach.core.config import get_settings

    student = _create_student(client)
    monkeypatch.setenv("PGN_MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    resp = _upload(client, student["id"], b"[" + b"x" * (1024 * 1024 + 10) + b"]")
    assert resp.status_code == 413


def test_path_traversal_filename_is_sanitized(client, mixed_pgn, db):
    from chesscoach.db.models import SourceFile

    student = _create_student(client)
    resp = _upload(client, student["id"], mixed_pgn, filename="../../secret/games.pgn")
    assert resp.status_code == 201
    source = db.scalar(select(SourceFile))
    assert source.original_filename == "games.pgn"


def test_cross_user_access_denied(client, mixed_pgn, make_user, db):
    student = _create_student(client)
    report = _upload(client, student["id"], mixed_pgn).json()
    game_id = report["games"][0]["game_id"]

    make_user("other-coach@example.com", UserRole.COACH)
    other = {"X-Dev-User-Email": "other-coach@example.com"}
    assert client.get(f"{API}/students/{student['id']}", headers=other).status_code == 403
    assert client.get(f"{API}/students/{student['id']}/games", headers=other).status_code == 403
    assert client.get(f"{API}/games/{game_id}", headers=other).status_code == 403
    assert _upload(client, student["id"], mixed_pgn, headers=other).status_code == 403
    assert client.get(f"{API}/students", headers=other).json()["total"] == 0


OWN_GAMES = b"""[Event "Online"]
[Date "2024.05.02"]
[White "ovindu_m"]
[Black "Rival"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0

[Event "Online"]
[Date "2024.05.03"]
[White "Anon1"]
[Black "Anon2"]
[Result "0-1"]

1. d4 d5 0-1
"""


def test_students_add_and_analyze_games_coaches_monitor(client, mixed_pgn, make_user, db):
    student = _create_student(client)
    other = _create_student(client, "Other", ["Opponent A"])
    _upload(client, other["id"], OWN_GAMES)  # a file this student has never imported
    me = client.as_student(student["id"])

    # Coaches do not add or analyze games: they monitor what the student adds.
    assert _upload(client, student["id"], OWN_GAMES, headers=COACH).status_code == 403

    report = _upload(client, student["id"], OWN_GAMES, headers=me)
    assert report.status_code == 201, report.text
    body = report.json()
    assert body["imported"] == 1 and body["needs_mapping"] == 1
    # Another student's earlier import of the same file is not revealed.
    assert body["file_previously_uploaded"] is False
    # The coach sees the student's games, marked as added by the student.
    games = client.get(f"{API}/students/{student['id']}/games").json()["items"]
    assert {g["added_by"] for g in games} == {"student"}

    unmatched = next(g["game_id"] for g in body["games"] if g["status"] == "needs_mapping")
    mapped = next(g["game_id"] for g in body["games"] if g["status"] == "imported")
    mapping = f"{API}/games/{unmatched}/mapping"
    assert client.patch(mapping, json={"student_color": "white"}, headers=COACH).status_code == 403
    resp = client.patch(mapping, json={"student_color": "white"}, headers=me)
    assert resp.status_code == 200 and resp.json()["mapping_status"] == "confirmed"
    assert client.post(f"{API}/games/{mapped}/analyze", headers=COACH).status_code == 403
    assert client.post(f"{API}/games/{mapped}/analyze", headers=me).status_code == 202
    # Lessons and exercises are the student's too; the coach can still read them.
    assert client.post(f"{API}/students/{student['id']}/coaching/lessons").status_code == 403
    assert client.post(f"{API}/students/{student['id']}/exercises").status_code == 403
    assert client.get(f"{API}/students/{student['id']}/coaching/sessions").status_code == 200

    # The coach's overview shows the student's activity.
    row = next(r for r in client.get(f"{API}/students").json()["items"] if r["id"] == student["id"])
    assert row["activity"]["games"] == row["activity"]["games_by_student"] == 2
    assert row["activity"]["last_student_upload"] is not None
    assert row["activity"]["has_login"] is True
    assert row["activity"]["mistakes"] == row["activity"]["open_mistakes"] == 0  # not analyzed

    # The student stays confined to their own record, with no coach-only actions.
    assert _upload(client, other["id"], mixed_pgn, headers=me).status_code == 403
    assert client.post(f"{API}/students", json={"display_name": "x"}, headers=me).status_code == 403
    assert (
        client.delete(
            f"{API}/students/{student['id']}", params={"confirm": "Ovindu"}, headers=me
        ).status_code
        == 403
    )


def test_unknown_student_is_404(client):
    resp = client.get(f"{API}/students/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_audit_events_recorded(client, mixed_pgn, db):
    student = _create_student(client)
    _upload(client, student["id"], mixed_pgn)
    actions = set(db.scalars(select(AuditEvent.action)).all())
    assert {"student.create", "games.import"} <= actions
