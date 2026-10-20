import { useState } from "react";

import { post, type CoachingSession, type Lesson, type Page } from "../../api";
import { LessonView } from "../../components/LessonView";
import { ActionButton, Empty, ErrorBox, Loading } from "../../components/ui";
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

export function CoachingTab({ studentId }: { studentId: string }) {
  const { data, error, loading, reload } = useLoad<Page<CoachingSession>>(`/students/${studentId}/coaching/sessions`);
  const [selected, setSelected] = useState<CoachingSession | null>(null);
  const current = selected ?? data?.items[0] ?? null;

  return (
    <section>
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
      {loading && <Loading />}
      <ErrorBox error={error} />
      {data && data.items.length === 0 && <Empty>No lessons yet.</Empty>}
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
