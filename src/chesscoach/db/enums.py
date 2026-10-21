"""Validated constants shared by models, services and API schemas."""

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    COACH = "coach"
    STUDENT = "student"


class AccessLevel(StrEnum):
    COACH = "coach"  # may view, import, review
    SELF = "self"  # the student's own account


class Color(StrEnum):
    WHITE = "white"
    BLACK = "black"


class GameResult(StrEnum):
    WHITE_WIN = "1-0"
    BLACK_WIN = "0-1"
    DRAW = "1/2-1/2"
    UNKNOWN = "*"


class ImportStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class MappingStatus(StrEnum):
    MAPPED = "mapped"  # resolved automatically from a unique alias match
    CONFIRMED = "confirmed"  # resolved manually by a coach
    UNMATCHED = "unmatched"  # no side matched a student alias
    AMBIGUOUS = "ambiguous"  # both sides matched; needs a coach decision


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisPass(StrEnum):
    BASELINE = "baseline"
    CRITICAL = "critical"


class GamePhase(StrEnum):
    OPENING = "opening"
    MIDDLEGAME = "middlegame"
    ENDGAME = "endgame"


class EvidenceType(StrEnum):
    MOVE_QUALITY = "move_quality"
    MOTIF = "motif"
    SKILL_INFERENCE = "skill_inference"


class ReviewStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CORRECTED = "corrected"


class ProfileState(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EMERGING_PATTERN = "emerging_pattern"
    RECURRING_WEAKNESS = "recurring_weakness"
    NO_ISSUE_DETECTED = "no_issue_detected"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    RETIRED = "retired"


class ValidationStatus(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    FALLBACK = "fallback"


class OpportunityOutcome(StrEnum):
    CONVERTED = "converted"  # the student found the key move (or an equally good one)
    MISSED = "missed"  # the student played something clearly worse


class ExercisePurpose(StrEnum):
    REVIEW = "review"  # a position where the student went wrong on this skill
    PRACTICE = "practice"  # another position from their games that tests the skill


class ExerciseStatus(StrEnum):
    OPEN = "open"
    SOLVED = "solved"
    FAILED = "failed"  # attempts exhausted; solution revealed
    REVEALED = "revealed"  # student gave up; solution revealed


class PuzzleStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"  # the full solution line was played
    REVEALED = "revealed"  # the student gave up and saw the solution


class PuzzleResult(StrEnum):
    """The first decision on a puzzle, which is what the puzzle rating counts (as on Lichess)."""

    SOLVED = "solved"
    FAILED = "failed"
