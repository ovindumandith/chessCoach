import { useState } from "react";

import { post, type CoachingSession, type Lesson, type Page } from "../../api";
import { LessonView } from "../../components/LessonView";
import { ActionButton, Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { useLoad } from "../../hooks";

interface LessonResponse {
  session: CoachingSession;
  used_fallback: boolean;
  lesson: Lesson;
}

function source(s: CoachingSession): string {
  return s.model_provider === "template"
    ? "Built from your game evidence (template)."
    : `Written by ${s.model_id} and checked against your game evidence.`;
}

/** Lessons. The student generates them; the coach reads every lesson the student got. */
export function CoachingTab({ studentId, canGenerate }: { studentId: string; canGenerate: boolean }) {
  const { data, error, loading, reload } = useLoad<Page<CoachingSession>>(`/students/${studentId}/coaching/sessions`);
  const [selected, setSelected] = useState<CoachingSession | null>(null);
  const current = selected ?? data?.items[0] ?? null;

  return (
    <section>
      {canGenerate ? (
        <ActionButton
          className="primary"
          onClick={async () => {
            const res = await post<LessonResponse>(`/students/${studentId}/coaching/lessons`);
            setSelected(res.session);
            await reload();
          }}
        >
          New lesson
        </ActionButton>
      ) : (
        <p className="muted small">
          The AI coach's training recommendations your student asked for, in full: what to work on, positions from their
          games, and the exercises recommended. Each shows the model that wrote it and whether it passed validation
          against their game evidence.
        </p>
      )}
      {loading && <Loading />}
      <ErrorBox error={error} />
      {data && data.items.length === 0 && (
        <Empty>{canGenerate ? "No lessons yet. Ask for one once your games are analyzed." : "Your student has not asked for a recommendation yet."}</Empty>
      )}
      {current && !canGenerate && (
        <p className="small" data-testid="lesson-meta">
          <b>{new Date(current.created_at).toLocaleString()}</b> · {current.model_provider} {current.model_id} ·
          validation <Badge kind={current.validation_status === "valid" ? "ok" : "warn"}>{current.validation_status}</Badge>
        </p>
      )}
      {current && <LessonView lesson={current.response_json} source={source(current)} />}
      {data && data.items.length > 1 && (
        <details>
          <summary>Earlier lessons</summary>
          <ul>
            {data.items.map((s) => (
              <li key={s.id}>
                <button className="link" onClick={() => setSelected(s)}>
                  {new Date(s.created_at).toLocaleString()}: {s.response_json.objective}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
