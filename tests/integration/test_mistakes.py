"""The student's mistakes grouped by game, acknowledgements, and "flagged again"."""

from tests.integration.test_recurring_mistakes import games  # noqa: F401  (fixture)

API = "/api/v1"


def mistakes(client, sid, headers=None, **params):
    return client.get(f"{API}/students/{sid}/mistakes", params=params, headers=headers)


def ack_url(game_id, ply):
    return f"{API}/games/{game_id}/mistakes/{ply}/acknowledgement"


def test_mistakes_are_grouped_by_game_newest_first(client, games):  # noqa: F811
    s, ids = games
    body = mistakes(client, s["id"], client.as_student(s["id"])).json()
    assert body["total_games"] == 4
    assert [g["opponent"] for g in body["games"]] == ["Dave", "Carol", "Bob", "Alice"]
    dave = body["games"][0]
    qe2 = next(m for m in dave["mistakes"] if m["san"] == "Qe2")
    assert (qe2["ply"], qe2["move_number"]) == (7, 4)
    assert qe2["verdict"] == "blunder" and qe2["best_move_san"] == "Qxf7#"
    assert qe2["reasons"]  # the board-derived "why"
    mate = next(t for t in qe2["types"] if t["subskill_code"] == "mating_patterns")
    assert [e["opponent"] for e in mate["earlier"]] == ["Alice", "Carol"]
    assert qe2["acknowledged_at"] is None and qe2["flagged_again"] is None
    # The game with the mate found has no mistake on move 4.
    bob = next(g for g in body["games"] if g["opponent"] == "Bob")
    assert all(m["san"] != "Qxf7#" for m in bob["mistakes"])
    # Paging over games.
    page = mistakes(client, s["id"], limit=2, offset=2).json()
    assert [g["opponent"] for g in page["games"]] == ["Bob", "Alice"]


def test_acknowledged_mistake_is_flagged_when_it_happens_again(client, games):  # noqa: F811
    s, ids = games
    me = client.as_student(s["id"])
    assert client.put(ack_url(ids[0], 7), headers=me).status_code == 200  # Alice game, 4.Qe2
    assert client.put(ack_url(ids[0], 7), headers=me).status_code == 200  # idempotent

    games_by = {g["opponent"]: g for g in mistakes(client, s["id"], me).json()["games"]}
    alice = next(m for m in games_by["Alice"]["mistakes"] if m["ply"] == 7)
    assert alice["acknowledged_at"] is not None and games_by["Alice"]["acknowledged"] == 1
    # Later games with the same kind of mistake are flagged, pointing at the acknowledged one.
    for later in ("Carol", "Dave"):
        m = next(m for m in games_by[later]["mistakes"] if m["ply"] == 7)
        assert m["flagged_again"]["opponent"] == "Alice"
        assert m["acknowledged_at"] is None
    # The coach sees the acknowledgement, read-only.
    coach_view = {g["opponent"]: g for g in mistakes(client, s["id"]).json()["games"]}
    assert coach_view["Alice"]["acknowledged"] == 1
    row = next(r for r in client.get(f"{API}/students").json()["items"] if r["id"] == s["id"])
    assert row["activity"]["open_mistakes"] == row["activity"]["mistakes"] - 1

    # Undo.
    assert client.delete(ack_url(ids[0], 7), headers=me).status_code == 204
    alice = next(
        m
        for g in mistakes(client, s["id"], me).json()["games"]
        if g["opponent"] == "Alice"
        for m in g["mistakes"]
        if m["ply"] == 7
    )
    assert alice["acknowledged_at"] is None


def test_only_the_student_acknowledges_their_own_moves(client, games, make_user):  # noqa: F811
    s, ids = games
    me = client.as_student(s["id"])
    assert client.put(ack_url(ids[0], 7)).status_code == 403  # the coach only monitors
    assert client.put(ack_url(ids[0], 8), headers=me).status_code == 422  # opponent's move
    assert client.put(ack_url(ids[0], 999), headers=me).status_code == 422
    make_user("other-coach@example.com")
    other = {"X-Dev-User-Email": "other-coach@example.com"}
    assert mistakes(client, s["id"], other).status_code == 403
    # Reviewing findings is not part of the product any more (admins label for research).
    finding = client.get(f"{API}/games/{ids[0]}/findings").json()["findings"][0]
    review = f"{API}/observations/{finding['observation_id']}/review"
    assert client.patch(review, json={"action": "confirm"}).status_code == 403
    assert client.patch(review, json={"action": "confirm"}, headers=me).status_code == 403
