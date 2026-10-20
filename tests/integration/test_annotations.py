"""Annotations for both sides of a game, in the standard + = White convention."""

from chesscoach.analysis.worker import run_once
from chesscoach.core.config import Settings
from tests.fakes import FakeAnalyzer

API = "/api/v1"
AS_WHITE = b"""[White "Me"]\n[Black "Opp"]\n[Result "*"]\n
1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qe2 *
"""
AS_BLACK = b"""[White "Opp"]\n[Black "Me"]\n[Result "*"]\n
1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# *
"""


def setup(client, db, pgn):
    s = client.post(f"{API}/students", json={"display_name": "S", "aliases": ["Me"]}).json()
    report = client.post(
        f"{API}/students/{s['id']}/games/import",
        headers=client.as_student(s["id"]),
        files={"file": ("g.pgn", pgn, "application/x-chess-pgn")},
    ).json()
    gid = report["games"][0]["game_id"]
    assert client.get(f"{API}/games/{gid}/annotations").status_code == 409  # not analyzed yet
    client.post(f"{API}/games/{gid}/analyze", headers=client.as_student.game(gid))
    while run_once(db, FakeAnalyzer(), Settings(stockfish_depth=8), "w"):
        pass
    return gid


def test_both_sides_are_annotated(client, db):
    gid = setup(client, db, AS_WHITE)
    body = client.get(f"{API}/games/{gid}/annotations").json()
    assert body["student_color"] == "white"
    assert body["evaluation_convention"].startswith("+ = White")
    sides = {a["ply"]: a["side"] for a in body["annotations"]}
    assert sides == {
        1: "student",
        2: "opponent",
        3: "student",
        4: "opponent",
        5: "student",
        6: "opponent",
        7: "student",
    }
    qe2 = body["annotations"][-1]
    assert (qe2["san"], qe2["label"], qe2["symbol"]) == ("Qe2", "Missed a forced mate", "??")
    assert qe2["eval_before"] == {"cp": None, "mate": 1}  # White (the student) had mate in 1
    assert qe2["reasons"] == ["Qxf7# would have forced mate in 1: Qxf7#."]
    nf6 = next(a for a in body["annotations"] if a["ply"] == 6)
    assert nf6["san"] == "Nf6" and nf6["side"] == "opponent"
    assert nf6["verdict"] == "blunder"  # 3...Nf6?? allowed mate in one
    assert nf6["eval_after"]["mate"] == 1  # White mates in 1, in White's point of view


def test_signs_follow_white_when_the_student_is_black(client, db):
    gid = setup(client, db, AS_BLACK)
    body = client.get(f"{API}/games/{gid}/annotations").json()
    assert body["student_color"] == "black"
    nf6 = next(a for a in body["annotations"] if a["ply"] == 6)
    assert nf6["side"] == "student" and nf6["label"] == "Allowed a forced mate"
    assert nf6["eval_after"]["mate"] == 1  # + means White, even though the student is Black
    mate = next(a for a in body["annotations"] if a["ply"] == 7)
    assert mate["side"] == "opponent" and mate["reasons"] == ["Qxf7# is checkmate."]
    assert mate["eval_after"] == {"cp": None, "mate": 0, "mated": "black"}
    assert body["win_chance_white"]["7"] == 1.0


def test_access_control(client, db, make_user):
    gid = setup(client, db, AS_WHITE)
    make_user("other@example.com")
    resp = client.get(
        f"{API}/games/{gid}/annotations", headers={"X-Dev-User-Email": "other@example.com"}
    )
    assert resp.status_code == 403
