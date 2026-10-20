"""classifier-v1: turn stored engine evidence into candidate observations and opportunities.

Each candidate is one of three evidence types, which are never merged:
- MOTIF: a tactical pattern verified on the board AND backed by the engine.
- SKILL_INFERENCE: a transparent context rule (phase, advantage, clock). Lower confidence.
- MOVE_QUALITY: an engine-confirmed error that nothing above explains. It is stored as
  `unclassified`, never given a guessed cause.

Confidence values are ordinal heuristics (0.8 high, 0.5 medium, 0.3 low), NOT calibrated
probabilities. All candidates start as `candidate` and need coach review to count as
ground truth.
"""

import re
from dataclasses import dataclass, field

import chess

from chesscoach.analysis.scores import Evaluation, MateTransition, win_probability
from chesscoach.classification.motifs import MOTIFS_VERSION, detect_allowed, detect_missed
from chesscoach.classification.taxonomy import UNCLASSIFIED
from chesscoach.db.enums import EvidenceType, GamePhase, OpportunityOutcome

CLASSIFIER_VERSION = "classifier-v1"

# Win-probability thresholds (0-1 scale). Bands follow Lichess's accuracy categories
# (inaccuracy/mistake/blunder at 10/20/30 points on its -100..100 winning-chances scale).
# All of these are untested starting points to calibrate against coach labels.
THRESHOLDS = {
    "inaccuracy": 0.05,
    "mistake": 0.10,
    "blunder": 0.15,
    "motif_min_loss": 0.08,  # a missed/allowed motif must have cost at least this
    "opportunity_min_gap": 0.08,  # best line must beat the 2nd-best by this to be "needed"
    "winning_wp": 0.80,  # about +375cp
    "defensive_min_wp": 0.20,
    "only_move_gap": 0.30,
    "time_trouble_seconds": 60,
    "time_trouble_fraction": 0.10,
}

CONFIDENCE = {"high": 0.8, "medium": 0.5, "low": 0.3}

TACTICAL = "tactical_awareness"


@dataclass
class MoveEvidence:
    fen_before: str
    fen_after: str
    uci_move: str
    phase: GamePhase
    eval_before: Evaluation
    best_move_uci: str | None
    win_prob_loss: float
    features: dict
    clock_before_ms: int | None = None
    cp_loss: int | None = None


@dataclass
class GameContext:
    base_time_seconds: int | None = None


@dataclass
class ObservationDraft:
    skill_code: str
    subskill_code: str | None
    evidence_type: EvidenceType
    severity: float
    confidence: float | None
    details: dict = field(default_factory=dict)


@dataclass
class OpportunityDraft:
    skill_code: str
    subskill_code: str | None
    outcome: OpportunityOutcome
    details: dict = field(default_factory=dict)


@dataclass
class Classification:
    observations: list[ObservationDraft] = field(default_factory=list)
    opportunities: list[OpportunityDraft] = field(default_factory=list)


def versions() -> dict:
    return {"classifier_version": CLASSIFIER_VERSION, "motifs_version": MOTIFS_VERSION}


def severity_band(wp_loss: float) -> str | None:
    if wp_loss >= THRESHOLDS["blunder"]:
        return "blunder"
    if wp_loss >= THRESHOLDS["mistake"]:
        return "mistake"
    if wp_loss >= THRESHOLDS["inaccuracy"]:
        return "inaccuracy"
    return None


def parse_base_time(time_control: str | None) -> int | None:
    """Base time in seconds from a PGN TimeControl like '600+5' or '300'."""
    if not time_control:
        return None
    match = re.match(r"^(\d+)(?:\+\d+)?$", time_control.strip())
    return int(match.group(1)) if match else None


def classify_move(m: MoveEvidence, ctx: GameContext) -> Classification:
    out = Classification()
    f = m.features
    if f.get("legal_moves") == 1:
        return out  # forced: no decision was made

    wp_loss = m.win_prob_loss or 0.0
    band = severity_band(wp_loss)
    transition = MateTransition(f.get("mate_transition", MateTransition.NONE))
    played_best = bool(f.get("played_best"))
    wp_before = win_probability(m.eval_before)
    base = {
        "band": band,
        "phase": m.phase.value,
        "win_prob_loss": wp_loss,
        "cp_loss": m.cp_loss,
        "mate_transition": transition.value,
    }

    _missed_motifs(m, out, base, wp_loss, transition, played_best)
    _allowed_motifs(m, out, base, wp_loss, transition)
    if band in ("mistake", "blunder") or (band and _time_trouble(m, ctx)):
        _inferences(m, ctx, out, base, band, wp_before, played_best)

    if band and not out.observations:
        out.observations.append(
            ObservationDraft(
                UNCLASSIFIED,
                None,
                EvidenceType.MOVE_QUALITY,
                wp_loss,
                None,
                {**base, "reason": "engine-confirmed error with no verified cause"},
            )
        )
    return out


def _missed_motifs(m, out, base, wp_loss, transition, played_best) -> None:
    motifs = detect_missed(m.fen_before, m.best_move_uci, m.eval_before.mate)
    gap = m.features.get("only_move_gap_wp")
    for motif in motifs:
        is_mate = motif.subskill == "mating_patterns"
        needed = is_mate or (gap is not None and gap >= THRESHOLDS["opportunity_min_gap"])
        if is_mate:
            missed = transition in (MateTransition.MISSED_MATE, MateTransition.MATE_TO_MATED)
            converted = not missed
        else:
            converted = played_best or wp_loss < THRESHOLDS["inaccuracy"]
            missed = not converted and wp_loss >= THRESHOLDS["motif_min_loss"]
        details = {**motif.details, "motif_kind": "missed", "best_move": m.best_move_uci}
        if needed and (converted or missed):
            outcome = OpportunityOutcome.CONVERTED if converted else OpportunityOutcome.MISSED
            out.opportunities.append(OpportunityDraft(TACTICAL, motif.subskill, outcome, details))
        if missed:
            out.observations.append(
                ObservationDraft(
                    TACTICAL,
                    motif.subskill,
                    EvidenceType.MOTIF,
                    wp_loss,
                    CONFIDENCE["high"],
                    {**base, **details, "confidence_label": "high"},
                )
            )


def _allowed_motifs(m, out, base, wp_loss, transition) -> None:
    if transition in (MateTransition.ALLOWED_MATE, MateTransition.MATE_TO_MATED):
        details = {**base, "motif_kind": "allowed", "confidence_label": "high"}
        out.observations.append(
            ObservationDraft(
                TACTICAL,
                "mating_patterns",
                EvidenceType.MOTIF,
                wp_loss,
                CONFIDENCE["high"],
                details,
            )
        )
        out.observations.append(
            ObservationDraft(
                "defensive_skills",
                "threat_prevention",
                EvidenceType.SKILL_INFERENCE,
                wp_loss,
                CONFIDENCE["medium"],
                {**base, "rule": "allowed_forced_mate", "confidence_label": "medium"},
            )
        )
        return
    if wp_loss < THRESHOLDS["motif_min_loss"]:
        return
    refutation = (m.features.get("refutation_pv") or [None])[0]
    if refutation is None and "refutation_pv" not in m.features:
        base = {**base, "note": "analysis predates refutation lines; allowed motifs not checked"}
    for motif in detect_allowed(m.fen_after, refutation):
        out.observations.append(
            ObservationDraft(
                TACTICAL,
                motif.subskill,
                EvidenceType.MOTIF,
                wp_loss,
                CONFIDENCE["high"],
                {
                    **base,
                    **motif.details,
                    "motif_kind": "allowed",
                    "refutation": refutation,
                    "confidence_label": "high",
                },
            )
        )


def _inferences(m, ctx, out, base, band, wp_before, played_best) -> None:
    serious = band in ("mistake", "blunder")
    gap = m.features.get("only_move_gap_wp")

    if serious and m.phase == GamePhase.ENDGAME:
        out.observations.append(
            ObservationDraft(
                "endgame_technique",
                _endgame_type(m.fen_before),
                EvidenceType.SKILL_INFERENCE,
                m.win_prob_loss,
                CONFIDENCE["low"],
                {**base, "rule": "error_in_endgame", "confidence_label": "low"},
            )
        )
    if serious and wp_before >= THRESHOLDS["winning_wp"]:
        out.observations.append(
            ObservationDraft(
                "winning_position_conversion",
                "preserving_advantage",
                EvidenceType.SKILL_INFERENCE,
                m.win_prob_loss,
                CONFIDENCE["medium"],
                {
                    **base,
                    "rule": "error_while_winning",
                    "win_prob_before": round(wp_before, 4),
                    "confidence_label": "medium",
                },
            )
        )
    elif (
        serious
        and not played_best
        and wp_before >= THRESHOLDS["defensive_min_wp"]
        and gap is not None
        and gap >= THRESHOLDS["only_move_gap"]
    ):
        out.observations.append(
            ObservationDraft(
                "defensive_skills",
                "finding_resources",
                EvidenceType.SKILL_INFERENCE,
                m.win_prob_loss,
                CONFIDENCE["medium"],
                {
                    **base,
                    "rule": "missed_only_move",
                    "only_move_gap_wp": gap,
                    "confidence_label": "medium",
                },
            )
        )
    if _time_trouble(m, ctx):
        out.observations.append(
            ObservationDraft(
                "practical_play",
                "time_management",
                EvidenceType.SKILL_INFERENCE,
                m.win_prob_loss,
                CONFIDENCE["medium"],
                {
                    **base,
                    "rule": "error_in_time_trouble",
                    "seconds_left": m.clock_before_ms / 1000,
                    "base_time_seconds": ctx.base_time_seconds,
                    "confidence_label": "medium",
                },
            )
        )


def _time_trouble(m: MoveEvidence, ctx: GameContext) -> bool:
    if m.clock_before_ms is None:
        return False
    seconds = m.clock_before_ms / 1000
    if seconds < THRESHOLDS["time_trouble_seconds"]:
        return True
    return bool(
        ctx.base_time_seconds
        and seconds < THRESHOLDS["time_trouble_fraction"] * ctx.base_time_seconds
    )


def _endgame_type(fen: str) -> str:
    board = chess.Board(fen)
    non_pawn = {
        pt
        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
        for color in chess.COLORS
        if board.pieces(pt, color)
    }
    if not non_pawn:
        return "pawn_endgames"
    if non_pawn == {chess.ROOK}:
        return "rook_endgames"
    return "general_endgames"
