// Plain-language reading of stored engine evidence. Thresholds match the server classifier
// (classification/classifier.py THRESHOLDS: inaccuracy 0.05, mistake 0.10, blunder 0.15
// win-probability loss), so the words here always agree with the findings.

import type { MoveAnalysis } from "./api";

export type VerdictKind = "best" | "good" | "inaccuracy" | "mistake" | "blunder";

export interface Verdict {
  kind: VerdictKind;
  label: string;
  symbol: string;
}

const VERDICTS: Record<VerdictKind, Verdict> = {
  best: { kind: "best", label: "Best move", symbol: "✓" },
  good: { kind: "good", label: "Good move", symbol: "" },
  inaccuracy: { kind: "inaccuracy", label: "Inaccuracy", symbol: "?!" },
  mistake: { kind: "mistake", label: "Mistake", symbol: "?" },
  blunder: { kind: "blunder", label: "Blunder", symbol: "??" },
};

const TRANSITION_LABEL: Record<string, string> = {
  missed_mate: "Missed a forced mate",
  allowed_mate: "Allowed a forced mate",
  mate_to_mated: "Turned a winning mate into a losing one",
};

export function verdictOf(m: MoveAnalysis): Verdict {
  const transition = m.features.mate_transition ?? "none";
  if (transition in TRANSITION_LABEL) {
    return { ...VERDICTS.blunder, label: TRANSITION_LABEL[transition] };
  }
  if (m.features.played_best) return VERDICTS.best;
  const loss = m.win_prob_loss ?? 0;
  if (loss >= 0.15) return VERDICTS.blunder;
  if (loss >= 0.1) return VERDICTS.mistake;
  if (loss >= 0.05) return VERDICTS.inaccuracy;
  return VERDICTS.good;
}

export function isMistake(v: Verdict): boolean {
  return v.kind === "inaccuracy" || v.kind === "mistake" || v.kind === "blunder";
}

/** "+1.34" style number, from the student's side. */
export function evalNumber(cp: number | null, mate: number | null, afterMove = false): string {
  if (mate !== null) {
    if (mate === 0 && afterMove) return "#";
    return mate > 0 ? `M${mate}` : `-M${-mate}`;
  }
  if (cp === null) return "?";
  return `${cp >= 0 ? "+" : ""}${(cp / 100).toFixed(2)}`;
}

/** Plain-language description of a position from the student's side. */
export function describe(cp: number | null, mate: number | null, afterMove = false): string {
  if (mate !== null) {
    if (mate === 0 && afterMove) return "you delivered checkmate";
    return mate > 0 ? `you had a forced mate in ${mate}` : `your opponent had a forced mate in ${-mate}`;
  }
  if (cp === null) return "unknown";
  const a = Math.abs(cp);
  const side = cp >= 0 ? "you" : "your opponent";
  if (a < 30) return "the position was about equal";
  if (a < 100) return `${side} had a slight edge`;
  if (a < 300) return `${side} had a clear advantage`;
  return `${side} ${cp >= 0 ? "were" : "was"} winning`;
}

/** Winning chances (0..1) from the student's side, same curve as the server. */
export function winChance(cp: number | null, mate: number | null): number | null {
  if (mate !== null) return mate >= 0 ? 1 : 0;
  if (cp === null) return null;
  return 1 / (1 + Math.exp(-0.00368208 * cp));
}

// ---------------------------------------------------------------------------- side-explicit text
// A bare "+1.50" is ambiguous: chess convention reads it as "White is better", while the
// stored analysis is from the student's side. Every evaluation shown to people therefore
// names the side that is better.

export type Side = "white" | "black";
const NAME: Record<Side, string> = { white: "White", black: "Black" };
export const other = (s: Side): Side => (s === "white" ? "black" : "white");

/** Convert a student-side evaluation to White's point of view. */
export function toWhitePov(cp: number | null, mate: number | null, student: Side) {
  const s = student === "white" ? 1 : -1;
  return { cp: cp === null ? null : s * cp, mate: mate === null ? null : s * mate };
}

/** "White +1.50", "Black mates in 3", "equal (0.12)" from White-POV values. `you` marks the
 * student's side, e.g. "Black +9.49 (you)". */
export function sideText(cpWhite: number | null, mateWhite: number | null, you?: Side): string {
  const tag = (side: Side) => (you === side ? " (you)" : "");
  if (mateWhite !== null) {
    if (mateWhite === 0) return "checkmate";
    const side: Side = mateWhite > 0 ? "white" : "black";
    return `${NAME[side]} mates in ${Math.abs(mateWhite)}${tag(side)}`;
  }
  if (cpWhite === null) return "?";
  if (Math.abs(cpWhite) < 20) return `equal (${(cpWhite / 100).toFixed(2)})`;
  const side: Side = cpWhite > 0 ? "white" : "black";
  return `${NAME[side]} +${(Math.abs(cpWhite) / 100).toFixed(2)}${tag(side)}`;
}

/** Side-explicit text for a stored (student-side) evaluation. */
export function studentEvalText(cp: number | null, mate: number | null, student: Side, afterMove = false): string {
  if (afterMove && mate === 0) return `${NAME[student]} (you) delivered checkmate`;
  const w = toWhitePov(cp, mate, student);
  return sideText(w.cp, w.mate, student);
}

/** Plain words that name the colours: "you (Black) were winning". */
export function describeFor(cp: number | null, mate: number | null, student: Side, afterMove = false): string {
  const you = `you (${NAME[student]})`;
  const them = `your opponent (${NAME[other(student)]})`;
  if (mate !== null) {
    if (mate === 0 && afterMove) return `${you} delivered checkmate`;
    return mate > 0 ? `${you} had a forced mate in ${mate}` : `${them} had a forced mate in ${-mate}`;
  }
  if (cp === null) return "unknown";
  const a = Math.abs(cp);
  if (a < 30) return "the position was about equal";
  const who = cp >= 0 ? you : them;
  if (a < 100) return `${who} had a slight edge`;
  if (a < 300) return `${who} had a clear advantage`;
  return `${who} ${cp >= 0 ? "were" : "was"} winning`;
}

/** Side to move in a FEN: the student's colour in any stored decision position. */
export function sideToMove(fen: string): Side {
  return fen.split(" ")[1] === "b" ? "black" : "white";
}

// ---------------------------------------------------------------------------- standard notation
// Numbers follow chess convention everywhere: + = White is better, − = Black is better.

/** "+1.50", "−1.50", "0.00", "#3" (White mates), "#−3" (Black mates), "#" (checkmate). */
export function fmtWhite(cp: number | null, mate: number | null): string {
  if (mate !== null) return mate === 0 ? "#" : mate > 0 ? `#${mate}` : `#−${-mate}`;
  if (cp === null) return "?";
  if (cp === 0) return "0.00";
  return `${cp > 0 ? "+" : "−"}${(Math.abs(cp) / 100).toFixed(2)}`;
}

export interface WhiteEval {
  cp: number | null;
  mate: number | null;
  mated?: "white" | "black";
}

/** Words for a White-POV evaluation, naming the student's colour. */
export function describeWhite(e: WhiteEval, student: Side, afterMove = false): string {
  if (e.mate === 0) {
    const winner: Side = e.mated === "black" ? "white" : "black";
    return winner === student ? `you (${NAME[student]}) delivered checkmate` : `your opponent (${NAME[winner]}) delivered checkmate`;
  }
  const s = student === "white" ? 1 : -1;
  return describeFor(e.cp === null ? null : s * e.cp, e.mate === null ? null : s * e.mate, student, afterMove);
}
