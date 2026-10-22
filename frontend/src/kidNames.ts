// Friendly names and icons for skills, for young players (and everyone else). The taxonomy
// names ("Winning-position conversion: Preserving advantages") stay in the coach views.

export const SKILL_ICON: Record<string, string> = {
  tactical_awareness: "⚔️",
  calculation: "🧮",
  positional_play: "🧭",
  opening_knowledge: "🚪",
  endgame_technique: "🏁",
  defensive_skills: "🛡️",
  winning_position_conversion: "🏆",
  practical_play: "⏱️",
  unclassified: "🔍",
};

const NAMES: Record<string, string> = {
  "tactical_awareness.forks": "Forks: attack two at once",
  "tactical_awareness.pins": "Pins",
  "tactical_awareness.skewers": "Skewers",
  "tactical_awareness.discovered_attacks": "Surprise attacks",
  "tactical_awareness.hanging_pieces": "Unprotected pieces",
  "tactical_awareness.mating_patterns": "Checkmate patterns",
  "calculation.forcing_variations": "Checks and captures first",
  "calculation.intermediate_moves": "Surprise in-between moves",
  "calculation.defensive_resources": "Finding a defence",
  "calculation.variation_accuracy": "Thinking ahead",
  "positional_play.pawn_structure": "Pawn chains",
  "positional_play.weak_squares": "Weak squares",
  "positional_play.piece_activity": "Active pieces",
  "positional_play.king_safety": "Keeping your king safe",
  "positional_play.strategic_planning": "Making a plan",
  "opening_knowledge.development": "Getting pieces out",
  "opening_knowledge.opening_principles": "Opening rules",
  "opening_knowledge.repertoire_deviations": "Your openings",
  "opening_knowledge.opening_traps": "Opening traps",
  "endgame_technique.king_activity": "Active king in the endgame",
  "endgame_technique.pawn_endgames": "Pawn endgames",
  "endgame_technique.rook_endgames": "Rook endgames",
  "endgame_technique.general_endgames": "Endgames",
  "endgame_technique.conversion": "Winning the endgame",
  "endgame_technique.defensive_holds": "Saving hard endgames",
  "defensive_skills.finding_resources": "Finding a rescue",
  "defensive_skills.threat_prevention": "Stopping threats",
  "defensive_skills.simplifying_under_pressure": "Trading when in trouble",
  "winning_position_conversion.preserving_advantage": "Keeping your advantage",
  "winning_position_conversion.practical_continuations": "Finishing the job",
  "winning_position_conversion.reducing_counterplay": "Stopping counterattacks",
  "practical_play.time_management": "Using your clock",
  "practical_play.decision_consistency": "Sticking to a plan",
  "practical_play.complex_positions": "Tricky positions",
  unclassified: "Moves to check again",
};

export function kidName(skill: string, subskill: string | null): string | undefined {
  return NAMES[subskill ? `${skill}.${subskill}` : skill];
}

export function skillIcon(skill: string): string {
  return SKILL_ICON[skill] ?? "♟️";
}

/** The first sentence of a text: the part a quick reader actually reads. */
export function firstSentence(text: string): string {
  const m = text.match(/^.*?[.!?](?=\s|$)/);
  return m ? m[0] : text;
}
