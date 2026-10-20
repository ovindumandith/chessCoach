import type { AnalysisState } from "../api";
import { Badge } from "./ui";

const LABEL: Record<AnalysisState, [string, string]> = {
  not_requested: ["not analyzed", ""],
  queued: ["queued", "warn"],
  running: ["analyzing…", "warn"],
  deepening: ["ready · deeper check running", "ok"],
  analyzed: ["analyzed", "ok"],
  failed: ["failed", "warn"],
};

export const IN_PROGRESS: AnalysisState[] = ["queued", "running", "deepening"];

export function AnalysisBadge({ state }: { state: AnalysisState | null }) {
  const [label, kind] = LABEL[state ?? "not_requested"];
  return <Badge kind={kind}>{label}</Badge>;
}
