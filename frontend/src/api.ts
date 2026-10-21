// Thin typed client for the ChessMentor API. The access token lives in sessionStorage
// (cleared when the tab closes) and is sent as a Bearer token, never as a cookie.

const BASE = "/api/v1";
const TOKEN_KEY = "chesscoach.token";

export class ApiError extends Error {
  status: number;
  details: Record<string, unknown>;
  constructor(status: number, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

export const token = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const t = token.get();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(BASE + path, { ...init, headers });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && t) {
      token.clear();
      onUnauthorized();
    }
    const err = body.error ?? {};
    throw new ApiError(res.status, err.message ?? body.detail ?? `HTTP ${res.status}`, err.details);
  }
  return body as T;
}

export const post = <T>(path: string, data?: unknown) =>
  api<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data) });
export const patch = <T>(path: string, data: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(data) });
export const put = <T>(path: string, data?: unknown) =>
  api<T>(path, { method: "PUT", body: data === undefined ? undefined : JSON.stringify(data) });
export const del = (path: string) => api<void>(path, { method: "DELETE" });

// ----------------------------------------------------------------------------- types

export type Role = "admin" | "coach" | "student";
export interface Me {
  id: string;
  email: string;
  role: Role;
  students: { student_id: string; access_level: "coach" | "self" }[];
}
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
export interface Student {
  id: string;
  display_name: string;
  rating_estimate: number | null;
  skill_level: string | null;
  aliases: string[];
  /** Coach overview counts; only on the student list. */
  activity?: {
    games: number;
    games_by_student: number;
    last_student_upload: string | null;
    mistakes: number;
    open_mistakes: number;
    has_login: boolean;
  } | null;
}
export interface Game {
  id: string;
  white_name: string;
  black_name: string;
  student_color: "white" | "black" | null;
  mapping_status: string;
  result: string;
  played_at: string | null;
  time_control: string | null;
  opening_eco: string | null;
  ply_count: number;
  analysis_status: AnalysisState | null;
  /** Who added the game: the student themself or a coach; null if not recorded. */
  added_by: "student" | "coach" | null;
}
export interface GameDetail extends Game {
  raw_pgn: string;
  pgn_headers: Record<string, string>;
}
export interface Annotation {
  ply: number;
  side: "student" | "opponent";
  san: string;
  fen_before: string;
  verdict: "best" | "good" | "inaccuracy" | "mistake" | "blunder";
  label: string;
  symbol: string;
  /** White's point of view: + = White better. */
  eval_before: { cp: number | null; mate: number | null; mated?: "white" | "black" };
  eval_after: { cp: number | null; mate: number | null; mated?: "white" | "black" };
  win_prob_loss: number;
  best_move_san: string | null;
  best_move_uci: string | null;
  best_line_san: string[];
  threat_uci: string | null;
  reasons: string[];
}
export interface GameAnnotations {
  game_id: string;
  student_color: "white" | "black";
  annotations: Annotation[];
  win_chance_white: Record<string, number | null>;
}
export type AnalysisState = "not_requested" | "queued" | "running" | "deepening" | "analyzed" | "failed";
export interface AnalysisStatus {
  game_id: string;
  state: AnalysisState;
  results_available: boolean;
  jobs_ahead: number | null;
  error_message: string | null;
  moves_to_analyze: number;
}
export interface ImportReport {
  imported: number;
  needs_mapping: number;
  duplicates: number;
  rejected: number;
  games: { index: number; status: string; white: string | null; black: string | null; reason: string | null }[];
}
export interface AnalysisJob {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  error_message: string | null;
  engine_name: string | null;
  engine_version: string | null;
  configuration: Record<string, unknown>;
}
export interface MoveAnalysis {
  ply: number;
  fen_before: string;
  san_move: string;
  uci_move: string;
  phase: string;
  eval_before_cp: number | null;
  eval_before_mate: number | null;
  eval_after_cp: number | null;
  eval_after_mate: number | null;
  best_move_uci: string | null;
  win_prob_loss: number | null;
  features: {
    pv_san?: string[];
    refutation_san?: string[];
    refutation_pv?: string[];
    critical?: boolean;
    mate_transition?: string;
    played_best?: boolean;
  };
}
export interface GameAnalysis {
  game_id: string;
  student_color: "white" | "black" | null;
  baseline: AnalysisJob;
  moves: MoveAnalysis[];
  critical: AnalysisJob | null;
  critical_moves: MoveAnalysis[];
}
/** One of the student's mistakes in a game (GET /students/{id}/mistakes). */
export interface Mistake {
  ply: number;
  move_number: number;
  san: string;
  verdict: string | null;
  label: string | null;
  symbol: string | null;
  eval_before: { cp: number | null; mate: number | null } | null;
  eval_after: { cp: number | null; mate: number | null } | null;
  best_move_san: string | null;
  best_line_san: string[];
  reasons: string[];
  types: {
    skill_code: string;
    subskill_code: string | null;
    motif_kind: string | null;
    evidence_type: string;
    earlier: { game_id: string; ply: number; move_number: number; opponent: string; played_at: string | null; acknowledged: boolean }[];
  }[];
  acknowledged_at: string | null;
  flagged_again: { game_id: string; ply: number; move_number: number; opponent: string; played_at: string | null } | null;
}
export interface GameMistakes {
  game_id: string;
  white_name: string;
  black_name: string;
  student_color: "white" | "black" | null;
  opponent: string;
  result: string;
  played_at: string | null;
  mistakes: Mistake[];
  acknowledged: number;
}
export interface MistakesPage {
  total_games: number;
  limit: number;
  offset: number;
  games: GameMistakes[];
}
export interface Weakness {
  id: string;
  game_id: string;
  skill_code: string;
  subskill_code: string | null;
  evidence_type: "motif" | "skill_inference" | "move_quality";
  severity: number | null;
  confidence: number | null;
  review_status: string;
  review_note: string | null;
  details: Record<string, unknown>;
  game_white: string;
  game_black: string;
  game_played_at: string | null;
  evidence: {
    ply: number;
    fen_before: string;
    san_move: string;
    uci_move: string;
    best_move_uci: string | null;
    best_line_san: string[];
    refutation_san: string[];
    eval_before_cp: number | null;
    eval_before_mate: number | null;
    eval_after_cp: number | null;
    eval_after_mate: number | null;
    phase: string;
  };
}
export interface SkillProfile {
  skill_code: string;
  subskill_code: string | null;
  state: string;
  error_rate: number | null;
  opportunity_count: number | null;
  error_count: number;
  games_affected: number;
  confidence: number | null;
  priority_score: number | null;
  evidence_summary: {
    provisional?: boolean;
    needs_diagnostic?: boolean;
    actionable?: boolean;
    components?: Record<string, number | null>;
    exercises?: { attempted: number; first_try_accuracy: number | null };
  };
}
export interface Profile {
  snapshot: {
    profile_version: number;
    generated_at: string;
    summary: { games_included: number; moves_analyzed: number };
  };
  stale: boolean;
  skills: SkillProfile[];
}
export interface Lesson {
  objective: string;
  skill_code: string;
  recurring_pattern: string;
  examples: { game_id: string; ply: number; fen: string; engine_best_move_uci: string | null; explanation: string }[];
  student_question: string;
  exercise_recommendation: string;
  follow_up_metric: string;
  uncertainty: string;
  verified_facts: string[];
  hypotheses: string[];
}
export interface CoachingSession {
  id: string;
  model_provider: string;
  model_id: string;
  validation_status: string;
  created_at: string;
  response_json: Lesson;
  objective: { skill_code: string; subskill_code: string | null } | null;
}
export interface Exercise {
  id: string;
  skill_code: string;
  subskill_code: string | null;
  purpose: "review" | "practice";
  status: "open" | "solved" | "failed" | "revealed";
  start_fen: string;
  side_to_move: "white" | "black";
  prompt: string;
  difficulty: string | null;
  max_attempts: number;
  attempts: { attempt_number: number; move_san: string; is_correct: boolean }[];
  hints_given: number;
  hints_available: number;
  solution: {
    accepted_moves_uci: string[];
    accepted_moves_san: string[];
    explanation: string | null;
    game_move: { san: string; eval_after: string } | null;
  } | null;
}
export interface ProgressSkill {
  skill_code: string;
  subskill_code: string | null;
  exercises: { assigned: number; attempted: number; solved_first_try: number; first_try_accuracy: number | null };
  profile_trend: { profile_version: number; state: string; error_rate: number | null; games_affected: number }[];
}
export interface Taxonomy {
  version: string;
  categories: Record<string, { name: string; subskills: Record<string, { name: string }> }>;
  special: Record<string, { name: string }>;
}

// ----------------------------------------------------------------------------- helpers

export function formatEval(cp: number | null, mate: number | null, afterMove = false): string {
  if (mate !== null) {
    if (mate === 0 && afterMove) return "#";
    return mate > 0 ? `M${mate}` : `-M${-mate}`;
  }
  if (cp === null) return "?";
  return `${cp >= 0 ? "+" : ""}${(cp / 100).toFixed(2)}`;
}

export function skillLabel(tax: Taxonomy | null, skill: string, sub: string | null): string {
  if (!tax) return sub ? `${skill}.${sub}` : skill;
  if (tax.special[skill]) return tax.special[skill].name;
  const cat = tax.categories[skill];
  if (!cat) return skill;
  return sub && cat.subskills[sub] ? `${cat.name}: ${cat.subskills[sub].name}` : cat.name;
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

// ----------------------------------------------------------------------------- puzzles
/** One Lichess puzzle given to the student (solution only once finished). */
export interface PuzzleView {
  id: string;
  set_id: string;
  position: number;
  skill_code: string;
  subskill_code: string | null;
  theme: string;
  rating: number;
  rating_deviation: number;
  themes: string[];
  fen: string;
  last_move: string;
  student_side: "white" | "black";
  status: "open" | "completed" | "revealed";
  result: "solved" | "failed" | null;
  wrong_moves: number;
  moves_left: number;
  solution: string[] | null;
  start_fen: string | null;
  lichess_url: string | null;
}
export interface PuzzleSet {
  set_id: string;
  student_id: string;
  skill_code: string;
  subskill_code: string | null;
  source: { game_id: string; ply: number; move_number: number; san: string | null; opponent: string; played_at: string | null } | null;
  created_at: string;
  rating_before: number;
  rating_now: number | null;
  solved: number;
  puzzles: PuzzleView[];
}
export interface PuzzleSetList {
  library_size: number;
  sets: PuzzleSet[];
}
