"""Lichess puzzles: import, sets of rising difficulty per mistake, solving, puzzle ratings."""

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from chesscoach.db.models import Puzzle, PuzzleAssignment, PuzzleTheme, StudentPuzzleRating
from chesscoach.puzzles import rating as glicko
from chesscoach.puzzles.importer import ImportFilter, import_puzzles, iter_file
from chesscoach.puzzles.selection import Candidate, pick, targets
from tests.integration.test_recurring_mistakes import games  # noqa: F401  (fixture)

API = "/api/v1"

# Before 3...Nf6?? (the opponent's move, played for the student), then 4.Qxf7# (the solution).
MATE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
MATE_MOVES = "g8f6 h5f7"
# A four-move line: opponent, student, opponent's reply, student.
LINE_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
LINE_MOVES = "e2e4 e7e5 g1f3 b8c6"


def row(
    pid,
    rating,
    *,
    themes=("mateIn1", "opening"),
    rd=75,
    pop=90,
    plays=1000,
    fen=MATE_FEN,
    moves=MATE_MOVES,
):
    return {
        "PuzzleId": pid,
        "GameId": f"game{pid}#7",
        "FEN": fen,
        "Moves": moves,
        "Rating": rating,
        "RatingDeviation": rd,
        "Popularity": pop,
        "NbPlays": plays,
        "Themes": list(themes),
        "OpeningTags": None,
    }


@pytest.fixture
def library(db):
    rows = [row(f"m{r}", r) for r in range(900, 2200, 50)]
    rows += [
        row(f"f{r}", r, themes=("fork", "middlegame"), fen=LINE_FEN, moves=LINE_MOVES)
        for r in range(900, 2200, 50)
    ]
    return import_puzzles(db, rows, source="test")


# --------------------------------------------------------------------------- import


def test_import_filters_caps_and_is_idempotent(db, tmp_path):
    rows = [
        row("ok1", 1500),
        row("shaky", 1500, rd=200),  # rating not reliable
        row("rare", 1500, plays=5),
        row("disliked", 1500, pop=-20),
        row("off", 1500, themes=("zugzwang",)),  # no skill is trained with this theme
        row("bad", 1500, moves="g8f6 h5h8"),  # illegal second move
        row("odd", 1500, moves="g8f6"),  # no player move
        row("ok2", 1510),
        row("ok3", 1520),  # third in the same (theme, band): over the cap of 2
    ]
    report = import_puzzles(db, rows, source="test", filt=ImportFilter(per_band=2))
    assert report.imported == 2 and report.skipped_full == 1
    assert report.skipped_quality == 3 and report.skipped_no_theme == 1
    assert report.skipped_invalid == 2
    stored = db.get(Puzzle, db.scalar(Puzzle.__table__.select().with_only_columns(Puzzle.id)))
    assert stored.source == "test" and stored.moves == MATE_MOVES
    assert db.query(PuzzleTheme).count() == 4  # every theme of both puzzles

    again = import_puzzles(db, [row("ok1", 1500)], source="test")
    assert again.imported == 0 and again.library_size == 2

    # The Hugging Face Parquet layout reads the same.
    path = tmp_path / "train.parquet"
    pq.write_table(pa.Table.from_pylist([row("pq1", 1700)]), path)
    assert import_puzzles(db, iter_file(path), source="hf").imported == 1


# --------------------------------------------------------------------------- pure logic


def test_targets_rise_and_pick_prefers_reliable_close_puzzles():
    assert targets(1500) == [1300, 1425, 1575, 1700]
    assert targets(450)[0] == 400  # clamped
    close_but_shaky = Candidate("a", "fork", 1510, 5, 99)  # target outside Rating ± RD
    covered = Candidate("b", "fork", 1540, 80, 50)
    assert pick([close_but_shaky, covered], 1500, None).puzzle_id == "b"
    assert pick([covered], 1500, above=1540) is None  # must be harder than the previous one


def test_rating_moves_with_results_and_rd_damps_it():
    assert glicko.updated(1500, 1500, 75, True, k=32) > 1500
    assert glicko.updated(1500, 1500, 75, False, k=32) < 1500
    sure = glicko.updated(1500, 1500, 60, True, k=32) - 1500
    unsure = glicko.updated(1500, 1500, 300, True, k=32) - 1500
    assert sure > unsure > 0
    # Beating a harder puzzle is worth more than an easier one.
    assert glicko.updated(1500, 1800, 75, True, k=32) > glicko.updated(1500, 1200, 75, True, k=32)


# --------------------------------------------------------------------------- sets and solving


def puzzles_url(game_id, ply=7):
    return f"{API}/games/{game_id}/mistakes/{ply}/puzzles"


def test_four_puzzles_per_mistake_getting_harder(client, games, library, db):  # noqa: F811
    s, ids = games
    me = client.as_student(s["id"])
    resp = client.post(puzzles_url(ids[0]), headers=me)  # 4.Qe2?? missed mate vs Alice
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["skill_code"], body["subskill_code"]) == ("tactical_awareness", "mating_patterns")
    assert body["source"]["san"] == "Qe2" and body["source"]["opponent"] == "Alice"
    ratings = [p["rating"] for p in body["puzzles"]]
    assert len(ratings) == 4 and ratings == sorted(set(ratings))  # strictly harder
    assert ratings[0] < 1500 < ratings[-1]  # around the default starting rating
    assert all(p["theme"] == "mateIn1" for p in body["puzzles"])
    first = body["puzzles"][0]
    # Shown after the opponent's move, solution hidden.
    assert first["last_move"] == "g8f6" and first["student_side"] == "white"
    assert first["solution"] is None and first["status"] == "open"
    # SQLite ignores VARCHAR lengths; PostgreSQL does not. Check stored strings fit.
    for column in ("selection_version", "theme", "skill_code", "subskill_code"):
        limit = PuzzleAssignment.__table__.c[column].type.length
        for a in db.query(PuzzleAssignment):
            assert len(getattr(a, column) or "") <= limit, column
    # Asking again reuses the unfinished set.
    assert client.post(puzzles_url(ids[0]), headers=me).json()["set_id"] == body["set_id"]
    # The coach monitors but does not solve or create.
    assert client.get(f"{API}/puzzle-sets/{body['set_id']}").status_code == 200
    assert client.post(puzzles_url(ids[0])).status_code == 403
    assert (
        client.post(f"{API}/puzzles/{first['id']}/moves", json={"move": "h5f7"}).status_code == 403
    )


def test_solving_updates_the_rating_and_the_next_set_is_harder(client, games, library, db):  # noqa: F811
    s, ids = games
    me = client.as_student(s["id"])
    body = client.post(puzzles_url(ids[0]), headers=me).json()
    p1, p2 = body["puzzles"][0], body["puzzles"][1]

    # Illegal moves are refused and not counted.
    assert (
        client.post(
            f"{API}/puzzles/{p1['id']}/moves", json={"move": "h5h8"}, headers=me
        ).status_code
        == 422
    )
    # A wrong (legal) move fails the puzzle for the rating; the student can still finish it.
    wrong = client.post(f"{API}/puzzles/{p1['id']}/moves", json={"move": "h5e5"}, headers=me).json()
    assert wrong["correct"] is False and wrong["puzzle"]["result"] == "failed"
    after_fail = db.query(StudentPuzzleRating).one().rating
    assert after_fail < 1500
    done = client.post(f"{API}/puzzles/{p1['id']}/moves", json={"move": "h5f7"}, headers=me).json()
    assert done["correct"] and done["puzzle"]["status"] == "completed"
    assert done["puzzle"]["result"] == "failed"  # the first decision counts
    assert done["puzzle"]["solution"] == ["h5f7"]
    assert done["puzzle"]["lichess_url"].startswith("https://lichess.org/training/")

    # Solving first time raises the rating.
    solved = client.post(
        f"{API}/puzzles/{p2['id']}/moves", json={"move": "h5f7"}, headers=me
    ).json()
    assert solved["puzzle"]["result"] == "solved"
    db.expire_all()
    assert db.query(StudentPuzzleRating).one().rating > after_fail

    # Solve the rest; the next set for this skill starts from the new, higher rating.
    for p in body["puzzles"][2:]:
        client.post(f"{API}/puzzles/{p['id']}/moves", json={"move": "h5f7"}, headers=me)
    db.expire_all()
    rating = db.query(StudentPuzzleRating).one().rating
    nxt = client.post(puzzles_url(ids[2]), headers=me).json()  # the same mistake vs Carol
    assert nxt["set_id"] != body["set_id"]
    assert nxt["rating_before"] == round(rating)
    first_new = nxt["puzzles"][0]["rating"]
    assert abs(first_new - (rating - 200)) <= 100  # starts 200 below the current rating
    assert not {p["id"] for p in nxt["puzzles"]} & {p["id"] for p in body["puzzles"]}


def test_multi_move_line_plays_the_opponents_reply(client, games, library):  # noqa: F811
    s, _ = games
    me = client.as_student(s["id"])
    body = client.post(
        f"{API}/students/{s['id']}/puzzle-sets",
        json={"skill_code": "tactical_awareness", "subskill_code": "forks"},
        headers=me,
    ).json()
    p = body["puzzles"][0]
    assert p["student_side"] == "black" and p["moves_left"] == 2
    step = client.post(f"{API}/puzzles/{p['id']}/moves", json={"move": "e7e5"}, headers=me).json()
    assert step["correct"] and step["reply"] == "g1f3" and step["puzzle"]["status"] == "open"
    assert step["puzzle"]["last_move"] == "g1f3" and step["puzzle"]["moves_left"] == 1
    end = client.post(f"{API}/puzzles/{p['id']}/moves", json={"move": "b8c6"}, headers=me).json()
    assert end["puzzle"]["status"] == "completed" and end["puzzle"]["result"] == "solved"
    # Giving up reveals the solution and counts as failed.
    q = body["puzzles"][1]
    shown = client.post(f"{API}/puzzles/{q['id']}/reveal", headers=me).json()
    assert shown["status"] == "revealed" and shown["result"] == "failed"
    assert shown["solution"] == ["e7e5", "g1f3", "b8c6"]
    listing = client.get(f"{API}/students/{s['id']}/puzzle-sets", headers=me).json()
    assert listing["library_size"] > 0 and listing["sets"][0]["solved"] == 1


def test_honest_refusals(client, games, db):  # noqa: F811
    s, ids = games
    me = client.as_student(s["id"])
    empty = client.post(puzzles_url(ids[0]), headers=me)
    assert empty.status_code == 409 and "library is empty" in empty.json()["error"]["message"]
    positional = client.post(
        f"{API}/students/{s['id']}/puzzle-sets",
        json={"skill_code": "positional_play", "subskill_code": "pawn_structure"},
        headers=me,
    )
    assert positional.status_code == 409 and "no matching Lichess puzzle theme" in positional.text
    assert client.post(puzzles_url(ids[0], ply=8), headers=me).status_code == 404  # no mistake
