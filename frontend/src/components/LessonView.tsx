import type { Lesson } from "../api";
import { Board } from "./Board";

export function LessonView({ lesson, source }: { lesson: Lesson; source?: string }) {
  return (
    <article className="lesson">
      <h3>{lesson.objective}</h3>
      {source && <p className="muted small">{source}</p>}
      <p>{lesson.recurring_pattern}</p>
      <div className="examples">
        {lesson.examples.map((ex) => (
          <figure key={`${ex.game_id}-${ex.ply}`} className="example">
            <Board fen={ex.fen} size={260} bestMove={ex.engine_best_move_uci} />
            <figcaption>{ex.explanation}</figcaption>
          </figure>
        ))}
      </div>
      <section className="callout">
        <strong>Your turn:</strong> {lesson.student_question}
      </section>
      <dl className="facts">
        <dt>Practice</dt>
        <dd>{lesson.exercise_recommendation}</dd>
        <dt>Follow-up</dt>
        <dd>{lesson.follow_up_metric}</dd>
        <dt>What we know</dt>
        <dd>
          <ul>
            {lesson.verified_facts.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </dd>
        <dt>What we think (not proven)</dt>
        <dd>
          <ul>
            {lesson.hypotheses.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        </dd>
        <dt>Uncertainty</dt>
        <dd>{lesson.uncertainty}</dd>
      </dl>
    </article>
  );
}
