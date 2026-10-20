"""The coach's overview of mistakes across all of their students."""

from tests.integration.test_privacy import setup_student

API = "/api/v1"


def overview(client, headers=None):
    return client.get(f"{API}/cohort/mistakes", headers=headers)


def test_mistakes_are_grouped_across_the_coachs_students(client, db, make_user):
    setup_student(client, db, "Alpha", ["Ovindu"])
    setup_student(client, db, "Beta", ["Ovindu"])  # the same games, a second student

    body = overview(client).json()
    assert body["students_total"] == 2 and body["students_with_findings"] == 2
    mate = next(g for g in body["groups"] if g["subskill_code"] == "mating_patterns")
    assert {s["display_name"] for s in mate["students"]} == {"Alpha", "Beta"}
    assert mate["findings"] == mate["open"] > 0 and mate["acknowledged"] == 0
    example = mate["examples"][0]
    assert example["game_id"] and example["san"] and example["ply"] > 0
    # The most widespread mistakes come first; unexplained errors (not a skill) come last.
    skills = [g for g in body["groups"] if g["skill_code"] != "unclassified"]
    counts = [len(g["students"]) for g in skills]
    assert counts == sorted(counts, reverse=True)
    assert body["groups"][: len(skills)] == skills

    # Acknowledgements by the student show up for the coach; findings stay.
    client.put(
        f"{API}/games/{example['game_id']}/mistakes/{example['ply']}/acknowledgement",
        headers=client.as_student(example["student_id"]),
    )
    mate = next(
        g for g in overview(client).json()["groups"] if g["subskill_code"] == "mating_patterns"
    )
    assert mate["acknowledged"] == 1 and mate["open"] == mate["findings"] - 1
    assert {s["display_name"] for s in mate["students"]} == {"Alpha", "Beta"}
    assert any(e["acknowledged"] for e in mate["examples"])


def test_only_coaches_see_their_own_students(client, db, make_user):
    s = setup_student(client, db, "Alpha", ["Ovindu"])
    # A student never sees other students' mistakes.
    assert overview(client, client.as_student(s["id"])).status_code == 403
    # Another coach sees none of this coach's students.
    make_user("other-coach@example.com")
    other = overview(client, {"X-Dev-User-Email": "other-coach@example.com"}).json()
    assert other == {
        "students_total": 0,
        "students_with_findings": 0,
        "classifier_version": other["classifier_version"],
        "groups": [],
    }
