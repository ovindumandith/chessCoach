import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, post, skillLabel, type ImprovementPlan, type PlanPosition, type PuzzleSet } from "../api";
import { useTaxonomy } from "../hooks";
import { firstSentence, kidName, skillIcon } from "../kidNames";
import { Board } from "./Board";
import { ActionButton, Badge, ErrorBox } from "./ui";

type Weakness = ImprovementPlan["plan"]["weaknesses"][number];

/**
 * An improvement plan, most important first: one mission with a board from the student's
 * own game, at most two more things to watch out for, a short training path and a few
 * golden rules. Everything else is folded away under "More for parents and coaches".
 */
export function PlanView({ p, canPractise = false }: { p: ImprovementPlan; canPractise?: boolean }) {
  const tax = useTaxonomy();
  const plan = p.plan;
  const [mission, ...others] = plan.weaknesses;
  const name = (w: Weakness) => kidName(w.skill_code, w.subskill_code) ?? w.title;

  return (
    <article className="kplan" data-testid="plan">
      <header className="kplan-head">
        <h2>{plan.title}</h2>
        <p className="kplan-summary">{plan.summary}</p>
      </header>

      {mission && (
        <MissionCard
          w={mission}
          name={name(mission)}
          positions={mission.evidence.map((e) => p.positions[`${e.game_id}:${e.ply}`]).filter(Boolean)}
          studentId={p.student_id}
          canPractise={canPractise}
        />
      )}

      {others.length > 0 && (
        <section className="kplan-section" aria-labelledby="watch-out">
          <h3 id="watch-out">👀 Also watch out for</h3>
          <div className="watch-grid">
            {others.slice(0, 2).map((w) => {
              const first = w.evidence[0];
              return (
                <div className="watch-card" key={`${w.skill_code}/${w.subskill_code}/${w.title}`}>
                  <span className="watch-icon" aria-hidden>
                    {skillIcon(w.skill_code)}
                  </span>
                  <div>
                    <p className="watch-name">{name(w)}</p>
                    <p className="small">{firstSentence(w.explanation)}</p>
                    {first && (
                      <Link className="small" to={`/games/${first.game_id}?ply=${first.ply}`}>
                        See it in your game →
                      </Link>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {plan.plan.length > 0 && (
        <TrainingPath
          p={p}
          // One name per idea: a step about a weakness uses the same friendly name as its card.
          label={(focus) => {
            const w = plan.weaknesses.find((x) => x.title === focus);
            return w ? name(w) : focus;
          }}
        />
      )}

      <div className="kplan-pair">
        {plan.habits.length > 0 && (
          <section className="kplan-section" aria-labelledby="golden-rules">
            <h3 id="golden-rules">✨ Golden rules for your games</h3>
            <ol className="golden-rules">
              {plan.habits.slice(0, 3).map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ol>
          </section>
        )}
        {plan.strengths.length > 0 && (
          <section className="kplan-section" aria-labelledby="superpowers">
            <h3 id="superpowers">⭐ Your superpowers</h3>
            <ul className="superpowers">
              {plan.strengths.slice(0, 3).map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <details className="kplan-more">
        <summary>More for parents and coaches</summary>
        <GrownUpDetails p={p} taxLabel={(w) => skillLabel(tax, w.skill_code, w.subskill_code)} />
      </details>
    </article>
  );
}

function MissionCard({
  w,
  name,
  positions,
  studentId,
  canPractise,
}: {
  w: Weakness;
  name: string;
  positions: PlanPosition[];
  studentId: string;
  canPractise: boolean;
}) {
  const [i, setI] = useState(0);
  const navigate = useNavigate();
  const pos = positions[i];
  const ev = w.evidence[i];
  return (
    <section className="mission" aria-labelledby="mission-title" data-testid="mission">
      <div className="mission-text">
        <p className="mission-label">🎯 Your mission</p>
        <h3 id="mission-title" className="mission-title">
          <span aria-hidden>{skillIcon(w.skill_code)}</span> {name}
        </h3>
        <p className="mission-why">{firstSentence(w.explanation)}</p>
        {pos && (
          <p className="mission-move" data-testid="mission-move">
            In your game against {pos.opponent} you played <b className="played">{pos.played_san}</b>.
            {pos.best_san && pos.best_san !== pos.played_san && (
              <>
                {" "}
                The star move was <b className="best">{pos.best_san}</b>!
              </>
            )}
          </p>
        )}
        <div className="mission-actions">
          {canPractise && w.skill_code !== "unclassified" && (
            <ActionButton
              className="primary big"
              onClick={async () => {
                const set = await post<PuzzleSet>(`/students/${studentId}/puzzle-sets`, {
                  skill_code: w.skill_code,
                  subskill_code: w.subskill_code,
                });
                navigate(`/puzzles/${set.set_id}`);
              }}
            >
              ▶ Play 4 puzzles
            </ActionButton>
          )}
          {ev && (
            <Link className="button-link big" to={`/games/${ev.game_id}?ply=${ev.ply}`}>
              🔍 See it in my game
            </Link>
          )}
        </div>
      </div>
      {pos && (
        <figure className="mission-board">
          <Board
            fen={pos.fen}
            orientation={pos.you_played}
            playedMove={pos.played_uci}
            bestMove={pos.best_uci}
            size="min(300px, 80vw)"
          />
          <figcaption className="small">
            <span className="arrow-key red" aria-hidden /> your move <span className="arrow-key green" aria-hidden /> star
            move
            {positions.length > 1 && (
              <span className="board-flip">
                <button aria-label="Previous example" onClick={() => setI((i + positions.length - 1) % positions.length)}>
                  ◀
                </button>
                {i + 1} / {positions.length}
                <button aria-label="Next example" onClick={() => setI((i + 1) % positions.length)}>
                  ▶
                </button>
              </span>
            )}
          </figcaption>
        </figure>
      )}
    </section>
  );
}

function readDone(planId: string): string[] {
  try {
    return JSON.parse(localStorage.getItem(`chesscoach.plan.${planId}.done`) ?? "[]");
  } catch {
    return [];
  }
}

/** The weekly plan as stepping stones; tick activities off as you go (kept in this browser). */
function TrainingPath({ p, label }: { p: ImprovementPlan; label: (focus: string) => string }) {
  const steps = p.plan.plan;
  const [open, setOpen] = useState(0);
  const [done, setDone] = useState<string[]>(() => readDone(p.id));
  const toggle = (key: string) => {
    const next = done.includes(key) ? done.filter((k) => k !== key) : [...done, key];
    setDone(next);
    try {
      localStorage.setItem(`chesscoach.plan.${p.id}.done`, JSON.stringify(next));
    } catch {
      /* storage unavailable: ticks last for this visit only */
    }
  };
  const step = steps[open];
  const stepDone = (i: number) => steps[i].activities.every((_, j) => done.includes(`${i}.${j}`));

  return (
    <section className="kplan-section" aria-labelledby="training-path">
      <h3 id="training-path">🗺️ Your training path</h3>
      <ol className="path" role="tablist">
        {steps.map((s, i) => (
          <li key={`${s.period}/${s.focus}`}>
            <button
              role="tab"
              aria-selected={i === open}
              className={`stone ${i === open ? "open" : ""} ${stepDone(i) ? "done" : ""}`}
              onClick={() => setOpen(i)}
            >
              <span className="stone-n">{stepDone(i) ? "✓" : i + 1}</span>
              <span className="stone-period">{s.period}</span>
              <span className="stone-focus">{label(s.focus)}</span>
            </button>
          </li>
        ))}
      </ol>
      {step && (
        <div className="path-detail" role="tabpanel">
          <ul className="todo">
            {step.activities.map((a, j) => {
              const key = `${open}.${j}`;
              return (
                <li key={key}>
                  <label>
                    <input type="checkbox" checked={done.includes(key)} onChange={() => toggle(key)} /> {a}
                  </label>
                </li>
              );
            })}
          </ul>
          <p className="small">
            🏁 <b>Goal:</b> {step.goal}
          </p>
        </div>
      )}
    </section>
  );
}

function GrownUpDetails({ p, taxLabel }: { p: ImprovementPlan; taxLabel: (w: Weakness) => string }) {
  const plan = p.plan;
  const [context, setContext] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const byLlm = p.model_provider !== "template";
  const lists: [string, string[]][] = [
    ["Daily and weekly routine", plan.training_routine],
    ["Study topics", plan.study_topics],
    ["Milestones", plan.milestones],
  ];
  return (
    <div className="grownup">
      <p className="small muted" data-testid="plan-meta">
        {new Date(p.created_at).toLocaleString()} ·{" "}
        {byLlm ? (
          <>
            written by <b>{p.model_id}</b> and checked against your games <Badge kind="ok">validated</Badge>
          </>
        ) : (
          <>
            built from a template <Badge kind="warn">no AI answer</Badge>
          </>
        )}{" "}
        · {p.games_included} of {p.games_total} analyzed games
        {p.token_usage?.input_tokens
          ? ` · ${p.token_usage.input_tokens + (p.token_usage.output_tokens ?? 0)} tokens`
          : ""}
      </p>
      <h4>All findings in this plan</h4>
      <ul>
        {plan.weaknesses.map((w) => (
          <li key={`${w.skill_code}/${w.subskill_code}/${w.title}`}>
            <b>{w.title}</b> <span className="muted small">({taxLabel(w)})</span>: {w.explanation}{" "}
            <span className="small">
              {w.evidence.map((e, i) => (
                <span key={`${e.game_id}/${e.ply}`}>
                  {i > 0 && ", "}
                  <Link to={`/games/${e.game_id}?ply=${e.ply}`}>
                    move {Math.ceil(e.ply / 2)}
                    {e.ply % 2 ? "" : "…"}
                  </Link>
                </span>
              ))}
            </span>
          </li>
        ))}
      </ul>
      {lists
        .filter(([, items]) => items.length > 0)
        .map(([title, items]) => (
          <div key={title}>
            <h4>{title}</h4>
            <ul>
              {items.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
        ))}
      {plan.puzzle_themes.length > 0 && (
        <>
          <h4>Lichess puzzle themes</h4>
          <p className="theme-chips">
            {plan.puzzle_themes.map((t) => (
              <Badge key={t}>{t}</Badge>
            ))}
          </p>
        </>
      )}
      <h4>What the data cannot tell</h4>
      <p className="muted">{plan.uncertainty}</p>
      <details
        onToggle={async (e) => {
          if (!(e.target as HTMLDetailsElement).open || context) return;
          try {
            const full = await api<ImprovementPlan>(`/improvement-plans/${p.id}?include_context=true`);
            setContext(JSON.stringify(full.context, null, 2));
          } catch (err) {
            setError(String(err));
          }
        }}
      >
        <summary className="small">What was sent to the AI</summary>
        <ErrorBox error={error} />
        {context && <pre className="plan-context">{context}</pre>}
      </details>
    </div>
  );
}
