import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  post,
  skillLabel,
  type CoachingSession,
  type Exercise,
  type Lesson,
  type Page,
  type PuzzleSet,
  type PuzzleSetList,
} from "../../api";
import { LessonView } from "../../components/LessonView";
import { ActionButton, Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { useLoad, useTaxonomy } from "../../hooks";

interface LessonResponse {
  session: CoachingSession;
  used_fallback: boolean;
  lesson: Lesson;
}

function source(s: CoachingSession): string {
  return s.model_provider === "template"
    ? "Built from your game evidence (template; no AI model is configured)."
    : `Written by ${s.model_id} and checked against your game evidence.`;
}

/**
 * Training, for the student: the AI coach's recommendation (what to work on, why, and which
 * exercises to do, grounded in their own mistakes), then the exercises themselves.
 */
export function ExercisesTab({ studentId }: { studentId: string }) {
  const sessions = useLoad<Page<CoachingSession>>(`/students/${studentId}/coaching/sessions`);
  const exercises = useLoad<Page<Exercise>>(`/students/${studentId}/exercises?limit=100`);
  const puzzleSets = useLoad<PuzzleSetList>(`/students/${studentId}/puzzle-sets`);
  const navigate = useNavigate();
  const tax = useTaxonomy();
  const [selected, setSelected] = useState<CoachingSession | null>(null);
  const current = selected ?? sessions.data?.items[0] ?? null;
  const goal = current?.objective ?? (current ? { skill_code: current.response_json.skill_code, subskill_code: null } : null);
  const list = exercises.data?.items ?? [];
  const forGoal = goal ? list.filter((e) => e.skill_code === goal.skill_code && (!goal.subskill_code || e.subskill_code === goal.subskill_code)) : [];
  const others = list.filter((e) => !forGoal.includes(e));

  async function recommend() {
    const res = await post<LessonResponse>(`/students/${studentId}/coaching/lessons`);
    setSelected(res.session);
    await sessions.reload();
  }

  async function practise() {
    await post(`/students/${studentId}/exercises`, goal ? { ...goal, count: 5 } : { count: 5 });
    await exercises.reload();
  }

  return (
    <section className="training">
      <div className="card recommendation" data-testid="recommendation">
        <div className="card-head">
          <h2 className="card-title">Recommended training</h2>
          <ActionButton className={current ? "" : "primary"} onClick={recommend}>
            {current ? "New recommendation" : "Get a recommendation"}
          </ActionButton>
        </div>
        <ErrorBox error={sessions.error} />
        {sessions.loading && !sessions.data && <Loading />}
        {sessions.data && !current && (
          <p className="muted">
            Your AI coach looks at the mistakes in your analyzed games, picks the one to work on first, explains it with
            positions from your own games and tells you which exercises to do.{" "}
            {list.length === 0 && (
              <>
                You need analyzed games first: <Link to="/?tab=games">add your games</Link>.
              </>
            )}
          </p>
        )}
        {current && (
          <>
            <LessonView lesson={current.response_json} source={source(current)} />
            <div className="row">
              <ActionButton className="primary" onClick={practise}>
                Practise this ({skillLabel(tax, goal?.skill_code ?? "", goal?.subskill_code ?? null)})
              </ActionButton>
              <ActionButton
                onClick={async () => {
                  const created = await post<PuzzleSet>(`/students/${studentId}/puzzle-sets`, goal);
                  navigate(`/puzzles/${created.set_id}`);
                }}
              >
                4 Lichess puzzles for this
              </ActionButton>
              <span className="muted small">
                Exercises come from the positions where you made this mistake; puzzles are new positions of the same
                kind, each harder than the last.
              </span>
            </div>
          </>
        )}
        {sessions.data && sessions.data.items.length > 1 && (
          <details>
            <summary>Earlier recommendations</summary>
            <ul>
              {sessions.data.items.map((s) => (
                <li key={s.id}>
                  <button className="link" onClick={() => setSelected(s)}>
                    {new Date(s.created_at).toLocaleString()}: {s.response_json.objective}
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <h2>Your puzzles</h2>
      {puzzleSets.data && puzzleSets.data.sets.length === 0 && (
        <Empty>
          {puzzleSets.data.library_size === 0
            ? "The puzzle library has not been loaded yet."
            : "No puzzles yet. Use “Puzzles like this” on a mistake, or “4 Lichess puzzles for this” above."}
        </Empty>
      )}
      {puzzleSets.data && puzzleSets.data.sets.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Skill</th>
              <th>For</th>
              <th>Ratings</th>
              <th>Solved</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {puzzleSets.data.sets.map((ps) => (
              <tr key={ps.set_id}>
                <td>{skillLabel(tax, ps.skill_code, ps.subskill_code)}</td>
                <td className="small">
                  {ps.source ? `${ps.source.move_number}${ps.source.ply % 2 ? "." : "…"} ${ps.source.san} vs ${ps.source.opponent}` : "recommendation"}
                </td>
                <td className="small evalnum">{ps.puzzles.map((p) => p.rating).join(" → ")}</td>
                <td>
                  <Badge kind={ps.solved === ps.puzzles.length ? "ok" : ""}>
                    {ps.solved}/{ps.puzzles.length}
                  </Badge>
                </td>
                <td>
                  <Link to={`/puzzles/${ps.set_id}`}>{ps.puzzles.some((p) => p.status === "open") ? "Solve" : "Review"}</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Your exercises</h2>
      <ErrorBox error={exercises.error} />
      {exercises.data && list.length === 0 && (
        <Empty>No exercises yet. Get a recommendation above, then press “Practise this”.</Empty>
      )}
      {forGoal.length > 0 && <ExerciseTable title="For this recommendation" rows={forGoal} tax={tax} />}
      {others.length > 0 && <ExerciseTable title={forGoal.length ? "Other exercises" : undefined} rows={others} tax={tax} />}
    </section>
  );
}

function ExerciseTable({ title, rows, tax }: { title?: string; rows: Exercise[]; tax: ReturnType<typeof useTaxonomy> }) {
  return (
    <>
      {title && <h3 className="small muted">{title}</h3>}
      <table>
        <thead>
          <tr>
            <th>Skill</th>
            <th>Type</th>
            <th>Difficulty</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((ex) => (
            <tr key={ex.id}>
              <td>{skillLabel(tax, ex.skill_code, ex.subskill_code)}</td>
              <td>{ex.purpose === "review" ? "From your mistakes" : "Practice"}</td>
              <td>{ex.difficulty ?? "–"}</td>
              <td>
                <Badge kind={ex.status === "solved" ? "ok" : ex.status === "open" ? "" : "warn"}>{ex.status}</Badge>
              </td>
              <td>
                <Link to={`/exercises/${ex.id}`}>{ex.status === "open" ? "Solve" : "View"}</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
