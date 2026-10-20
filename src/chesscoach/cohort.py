"""Coach overview: which mistakes their students make, across all of their students.

Read-only. Built from the current classifier version's findings; a move with several
observations of the same kind counts once. Each group also says how many of those mistakes
the students have acknowledged.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from chesscoach.classification.classifier import CLASSIFIER_VERSION
from chesscoach.classification.taxonomy import UNCLASSIFIED
from chesscoach.core.access import require_coach_role
from chesscoach.db.enums import AccessLevel, ReviewStatus, UserRole
from chesscoach.db.models import (
    Game,
    MoveAnalysis,
    Student,
    StudentAccess,
    User,
    WeaknessObservation,
)
from chesscoach.mistakes import acknowledged_moves


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _coached_students(db: Session, user: User) -> list[Student]:
    query = select(Student)
    if user.role != UserRole.ADMIN:
        query = query.join(StudentAccess, StudentAccess.student_id == Student.id).where(
            StudentAccess.user_id == user.id, StudentAccess.access_level == AccessLevel.COACH
        )
    return list(db.scalars(query.order_by(Student.display_name)))


def mistake_overview(db: Session, user: User, *, examples: int = 3) -> dict:
    """Mistake types across the coach's students, most widespread first."""
    require_coach_role(user)
    students = _coached_students(db, user)
    names = {s.id: s.display_name for s in students}
    acked = acknowledged_moves(db, list(names))
    rows = (
        db.execute(
            select(WeaknessObservation, MoveAnalysis, Game)
            .join(MoveAnalysis, MoveAnalysis.id == WeaknessObservation.move_analysis_id)
            .join(Game, Game.id == WeaknessObservation.game_id)
            .where(
                WeaknessObservation.student_id.in_(list(names)),
                WeaknessObservation.classifier_version == CLASSIFIER_VERSION,
                WeaknessObservation.review_status != ReviewStatus.REJECTED,
            )
        ).all()
        if names
        else []
    )

    groups: dict[tuple, dict] = {}
    for o, m, g in rows:
        group = groups.setdefault(
            (o.skill_code, o.subskill_code),
            {"skill_code": o.skill_code, "subskill_code": o.subskill_code, "moves": {}},
        )
        group["moves"].setdefault(
            (g.id, m.ply),
            {
                "student_id": o.student_id,
                "game": g,
                "ply": m.ply,
                "san": m.san_move,
                "ok": (g.id, m.ply) in acked,
            },
        )

    def recent(v: dict):
        g = v["game"]
        return (g.played_at is not None, g.played_at or date.min, g.created_at, v["ply"])

    out = []
    for group in groups.values():
        moves = list(group["moves"].values())
        per_student: dict[uuid.UUID, int] = {}
        for v in moves:
            per_student[v["student_id"]] = per_student.get(v["student_id"], 0) + 1
        acknowledged = sum(1 for v in moves if v["ok"])
        out.append(
            {
                "skill_code": group["skill_code"],
                "subskill_code": group["subskill_code"],
                "findings": len(moves),
                "acknowledged": acknowledged,
                "open": len(moves) - acknowledged,
                "students": [
                    {"student_id": str(sid), "display_name": names[sid], "findings": n}
                    for sid, n in sorted(per_student.items(), key=lambda kv: (-kv[1], names[kv[0]]))
                ],
                "examples": [
                    {
                        "student_id": str(v["student_id"]),
                        "display_name": names[v["student_id"]],
                        "game_id": str(v["game"].id),
                        "ply": v["ply"],
                        "move_number": (v["ply"] + 1) // 2,
                        "san": v["san"],
                        "played_at": _iso(v["game"].played_at),
                        "acknowledged": v["ok"],
                    }
                    for v in sorted(moves, key=recent, reverse=True)[:examples]
                ],
            }
        )
    # Unexplained engine errors are not a skill: listed last, whatever their count.
    out.sort(
        key=lambda g: (
            g["skill_code"] == UNCLASSIFIED,
            -len(g["students"]),
            -g["findings"],
            g["skill_code"],
        )
    )
    affected = {s["student_id"] for g in out for s in g["students"]}
    return {
        "students_total": len(students),
        "students_with_findings": len(affected),
        "classifier_version": CLASSIFIER_VERSION,
        "groups": out,
    }
