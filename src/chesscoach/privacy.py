"""Student data deletion (right to erasure).

Deletes a student and everything derived from their games, in dependency order. Several
evidence foreign keys deliberately have no ON DELETE CASCADE (so evidence is never
removed implicitly), which is why the order is explicit here.

Kept on purpose:
- Uploaded PGN files that still contain games of OTHER students.
- Audit events. They hold ids and counts, never names or PGN content.
- The student's own login is anonymised and deactivated rather than deleted, so audit
  rows that reference it stay valid but no longer identify anyone.

    python -m chesscoach.privacy delete-student <student-uuid> --confirm "<display name>"
"""

import argparse
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from chesscoach.core.access import require_student_access
from chesscoach.core.audit import record_audit
from chesscoach.core.config import get_settings
from chesscoach.core.errors import DomainError, NotFoundError, ValidationFailedError
from chesscoach.db.enums import AccessLevel, UserRole
from chesscoach.db.models import (
    AnalysisRun,
    CoachingSession,
    Exercise,
    ExerciseAttempt,
    Game,
    ImprovementPlan,
    LearningPlan,
    MistakeAcknowledgement,
    MoveAnalysis,
    ProfileSnapshot,
    PuzzleAssignment,
    SkillOpportunity,
    SourceFile,
    Student,
    StudentAccess,
    StudentPuzzleRating,
    StudentSkillProfile,
    User,
    WeaknessObservation,
)
from chesscoach.db.session import get_sessionmaker
from chesscoach.ingestion.storage import LocalFileStorage


def delete_student(
    db: Session,
    student_id: uuid.UUID,
    *,
    confirm_name: str,
    actor: User | None,
    storage: LocalFileStorage | None = None,
) -> dict:
    """Irreversibly delete a student's data. `confirm_name` must equal the display name."""
    if actor is not None:
        require_student_access(db, actor, student_id, coach_only=True)
    student = db.get(Student, student_id)
    if student is None:
        raise NotFoundError("Student not found")
    if confirm_name != student.display_name:
        raise ValidationFailedError("Confirmation does not match the student's name")
    storage = storage or LocalFileStorage(get_settings().storage_dir)

    game_ids = list(db.scalars(select(Game.id).where(Game.student_id == student_id)))
    run_ids = list(db.scalars(select(AnalysisRun.id).where(AnalysisRun.game_id.in_(game_ids))))
    source_ids = set(db.scalars(select(Game.source_file_id).where(Game.student_id == student_id)))
    self_users = list(
        db.scalars(
            select(User)
            .join(StudentAccess, StudentAccess.user_id == User.id)
            .where(
                StudentAccess.student_id == student_id,
                StudentAccess.access_level == AccessLevel.SELF,
                User.role == UserRole.STUDENT,
            )
        )
    )

    counts = {}

    def run(name, stmt):
        counts[name] = db.execute(stmt).rowcount or 0

    exercise_ids = select(Exercise.id).where(Exercise.student_id == student_id)
    run(
        "exercise_attempts",
        delete(ExerciseAttempt).where(ExerciseAttempt.exercise_id.in_(exercise_ids)),
    )
    run("exercises", delete(Exercise).where(Exercise.student_id == student_id))
    run(
        "weakness_observations",
        delete(WeaknessObservation).where(WeaknessObservation.student_id == student_id),
    )
    run(
        "skill_opportunities",
        delete(SkillOpportunity).where(SkillOpportunity.student_id == student_id),
    )
    run(
        "coaching_sessions", delete(CoachingSession).where(CoachingSession.student_id == student_id)
    )
    run("learning_plans", delete(LearningPlan).where(LearningPlan.student_id == student_id))
    run(
        "skill_profiles",
        delete(StudentSkillProfile).where(StudentSkillProfile.student_id == student_id),
    )
    run(
        "profile_snapshots", delete(ProfileSnapshot).where(ProfileSnapshot.student_id == student_id)
    )
    run(
        "improvement_plans",
        delete(ImprovementPlan).where(ImprovementPlan.student_id == student_id),
    )
    run(
        "puzzle_assignments",
        delete(PuzzleAssignment).where(PuzzleAssignment.student_id == student_id),
    )
    run(
        "student_puzzle_ratings",
        delete(StudentPuzzleRating).where(StudentPuzzleRating.student_id == student_id),
    )
    run(
        "mistake_acknowledgements",
        delete(MistakeAcknowledgement).where(MistakeAcknowledgement.student_id == student_id),
    )
    run("move_analyses", delete(MoveAnalysis).where(MoveAnalysis.analysis_run_id.in_(run_ids)))
    run("analysis_runs", delete(AnalysisRun).where(AnalysisRun.id.in_(run_ids)))
    run("games", delete(Game).where(Game.student_id == student_id))

    # PGN files are shared when one file held games of several students.
    files_to_remove = []
    for source_id in source_ids:
        still_used = db.scalar(
            select(func.count()).select_from(Game).where(Game.source_file_id == source_id)
        )
        if not still_used:
            source = db.get(SourceFile, source_id)
            files_to_remove.append(source.storage_key)
            db.delete(source)
    counts["source_files"] = len(files_to_remove)

    for user in self_users:
        db.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                email=f"deleted-{user.id}@deleted.invalid",
                password_hash=None,
                external_auth_id=None,
                is_active=False,
            )
        )
    counts["student_logins_anonymised"] = len(self_users)

    db.delete(student)  # cascades aliases and access rows
    record_audit(
        db,
        actor_user_id=actor.id if actor else None,
        action="student.delete",
        entity_type="student",
        entity_id=student_id,
        details=counts,
    )
    db.commit()

    # Remove files only after the database commit succeeded.
    for key in files_to_remove:
        storage.delete(key)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Irreversibly delete a student's data")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("delete-student")
    cmd.add_argument("student_id", type=uuid.UUID)
    cmd.add_argument("--confirm", required=True, help="The student's exact display name")
    args = parser.parse_args()
    with get_sessionmaker()() as db:
        try:
            print(delete_student(db, args.student_id, confirm_name=args.confirm, actor=None))
        except DomainError as exc:
            raise SystemExit(f"Not deleted: {exc.message}") from None


if __name__ == "__main__":
    main()
