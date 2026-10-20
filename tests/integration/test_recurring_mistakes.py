"""'You made the same mistake here before' links across a student's games."""

import pytest

from chesscoach.analysis.worker import run_once
from chesscoach.core.config import Settings
from tests.fakes import FakeAnalyzer

API = "/api/v1"


def game(n, date, white, black, moves):
    return (
        f'[Event "G{n}"]\n[Round "{n}"]\n[Date "{date}"]\n[White "{white}"]\n'
        f'[Black "{black}"]\n[Result "*"]\n\n{moves} *\n\n'
    )


MISSED = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qe2"
FOUND = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7#"
PGN = (
    game(1, "2024.01.10", "Me", "Alice", MISSED)
    + game(2, "2024.02.10", "Me", "Bob", FOUND)  # no mistake here
    + game(3, "2024.03.10", "Me", "Carol", MISSED)
    + game(4, "2024.04.10", "Me", "Dave", MISSED)
).encode()


@pytest.fixture
def games(client, db):
    s = client.post(f"{API}/students", json={"display_name": "S", "aliases": ["Me"]}).json()
    report = client.post(
        f"{API}/students/{s['id']}/games/import",
        files={"file": ("g.pgn", PGN, "application/x-chess-pgn")},
    ).json()
    ids = {g["index"]: g["game_id"] for g in report["games"]}
    for gid in ids.values():
        client.post(f"{API}/games/{gid}/analyze")
    while run_once(db, FakeAnalyzer(), Settings(stockfish_depth=8), "w"):
        pass
    return s, ids


def mate_finding(client, game_id):
    findings = client.get(f"{API}/games/{game_id}/findings").json()["findings"]
    return next(
        f
        for f in findings
        if f["subskill_code"] == "mating_patterns" and f["motif_kind"] == "missed"
    )


def test_links_the_same_mistake_in_other_games_earliest_first(client, games):
    _, ids = games
    f = mate_finding(client, ids[3])  # the Dave game, played last
    assert (f["ply"], f["san_move"], f["move_number"]) == (7, "Qe2", 4)
    elsewhere = f["same_mistake_elsewhere"]
    assert [e["opponent"] for e in elsewhere] == ["Alice", "Carol"]  # oldest first
    assert all(e["earlier"] for e in elsewhere)
    assert elsewhere[0] == {
        **elsewhere[0],
        "game_id": ids[0],
        "ply": 7,
        "san_move": "Qe2",
        "move_number": 4,
        "played_at": "2024-01-10",
    }
    assert f["same_mistake_count"] == 2


def test_later_games_are_marked_as_later(client, games):
    _, ids = games
    first = mate_finding(client, ids[0])
    assert [(e["opponent"], e["earlier"]) for e in first["same_mistake_elsewhere"]] == [
        ("Carol", False),
        ("Dave", False),
    ]


def test_game_without_the_mistake_is_never_linked(client, games):
    _, ids = games
    linked = {e["game_id"] for e in mate_finding(client, ids[3])["same_mistake_elsewhere"]}
    assert ids[1] not in linked  # the game where Qxf7# was found


def test_rejected_findings_are_not_linked(client, games):
    s, ids = games
    first = mate_finding(client, ids[0])
    client.patch(f"{API}/observations/{first['observation_id']}/review", json={"action": "reject"})
    linked = [e["opponent"] for e in mate_finding(client, ids[3])["same_mistake_elsewhere"]]
    assert linked == ["Carol"]


def test_unexplained_errors_are_not_matched(client, games):
    _, ids = games
    findings = client.get(f"{API}/games/{ids[3]}/findings").json()["findings"]
    for f in findings:
        if f["skill_code"] == "unclassified":
            assert f["same_mistake_elsewhere"] == []


def test_access_control(client, games, make_user):
    _, ids = games
    make_user("other@example.com")
    resp = client.get(
        f"{API}/games/{ids[0]}/findings", headers={"X-Dev-User-Email": "other@example.com"}
    )
    assert resp.status_code == 403
