import { useState } from "react";
import { Link } from "react-router-dom";

import { errorText, post, type ImprovementPlan, type PlanOverview } from "../../api";
import { PlanView } from "../../components/PlanView";
import { Empty, ErrorBox, Loading } from "../../components/ui";
import { useLoad } from "../../hooks";

/**
 * "Chess LLM": the student asks their AI coach for a plan, made from all their analyzed
 * games. Designed for young players first: one clear action, a playful wait, and the plan
 * itself shows the most important things first. Every plan is kept.
 */
export function ChessLlmTab({ studentId }: { studentId: string }) {
  const { data, error, loading, reload } = useLoad<PlanOverview>(`/students/${studentId}/improvement-plans`);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  if (loading && !data) return <Loading />;
  if (!data) return <ErrorBox error={error} />;
  const current = data.plans.find((p) => p.id === selected) ?? data.plans[0];
  const missing = Math.max(0, data.required_games - data.analyzed_games);
  const pawns = Math.max(data.required_games, Math.min(data.analyzed_games, 10));

  async function ask() {
    setBusy(true);
    setAskError(null);
    try {
      const created = await post<ImprovementPlan>(`/students/${studentId}/improvement-plans`);
      setSelected(created.id);
      await reload();
    } catch (e) {
      setAskError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="chess-llm">
      <div className="card ask-card" data-testid="plan-request">
        <div className="ask-text">
          <h2 className="ask-title">🤖 Ask your AI coach</h2>
          <p>Your coach looks at all your games and makes a plan just for you.</p>
          <div className="pawn-meter" aria-label={`${data.analyzed_games} of ${data.required_games} analyzed games`}>
            {Array.from({ length: pawns }, (_, k) => (
              <span key={k} className={k < data.analyzed_games ? "pawn on" : "pawn"} aria-hidden>
                ♟
              </span>
            ))}
          </div>
          <p className="small" data-testid="plan-eligibility">
            {data.eligible ? (
              <>{data.analyzed_games} analyzed games. Ready.</>
            ) : (
              <>
                {data.analyzed_games} of {data.required_games} analyzed games.{" "}
                {data.games_in_progress >= missing ? (
                  <>
                    {data.games_in_progress} more {data.games_in_progress === 1 ? "is" : "are"} still being analyzed;
                    come back in a moment.
                  </>
                ) : (
                  <>
                    Add {missing} more in <Link to="/?tab=games">My games</Link> to unlock your plan.
                  </>
                )}
              </>
            )}
            {data.eligible && data.games_in_progress > 0 && (
              <span className="muted"> ({data.games_in_progress} more still being analyzed.)</span>
            )}
          </p>
        </div>
        <button className="primary big ask-button" disabled={!data.eligible || busy} onClick={() => void ask()}>
          {busy ? "Thinking…" : "Get LLM recommendation"}
        </button>
      </div>
      <ErrorBox error={askError} />

      {busy && (
        <div className="thinking card" role="status" data-testid="thinking">
          <span className="thinking-knight" aria-hidden>
            ♞
          </span>
          <div>
            <p className="thinking-title">Your coach is studying your games…</p>
            <p className="muted small">This can take a minute or two. Every move it suggests is checked with Stockfish.</p>
          </div>
        </div>
      )}

      {!busy && data.plans.length === 0 && (
        <Empty>No plan yet. When you are ready, press the button to get your first one!</Empty>
      )}
      {!busy && current && <PlanView p={current} canPractise />}

      {data.plans.length > 1 && (
        <section className="plan-history">
          <label className="small">
            Earlier plans{" "}
            <select value={current?.id} onChange={(e) => setSelected(e.target.value)}>
              {data.plans.map((p) => (
                <option key={p.id} value={p.id}>
                  {new Date(p.created_at).toLocaleString()} · {p.model_provider === "template" ? "template" : p.model_id}
                </option>
              ))}
            </select>
          </label>
          <span className="muted small"> {data.plans.length} plans saved</span>
        </section>
      )}
    </section>
  );
}

/** The coach's read-only view of the student's AI improvement plans. */
export function CoachPlans({ studentId }: { studentId: string }) {
  const { data, error } = useLoad<PlanOverview>(`/students/${studentId}/improvement-plans`);
  const [selected, setSelected] = useState<string | null>(null);
  if (!data) return <ErrorBox error={error} />;
  const current = data.plans.find((p) => p.id === selected) ?? data.plans[0];
  return (
    <section className="chess-llm">
      <h2>AI improvement plans</h2>
      <p className="muted small">
        Plans your student asked for in their Chess LLM tab ({data.analyzed_games} analyzed games so far; at least{" "}
        {data.required_games} needed).
      </p>
      {data.plans.length === 0 && <Empty>Your student has not asked for an improvement plan yet.</Empty>}
      {data.plans.length > 1 && (
        <p className="small">
          {data.plans.map((p, i) => (
            <span key={p.id}>
              {i > 0 && " · "}
              <button className="link" aria-current={p.id === current?.id} onClick={() => setSelected(p.id)}>
                {new Date(p.created_at).toLocaleDateString()}
              </button>
            </span>
          ))}
        </p>
      )}
      {current && <PlanView p={current} />}
    </section>
  );
}
