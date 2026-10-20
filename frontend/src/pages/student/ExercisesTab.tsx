import { Link } from "react-router-dom";

import { post, skillLabel, type Exercise, type Page } from "../../api";
import { ActionButton, Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { useLoad, useTaxonomy } from "../../hooks";

export function ExercisesTab({ studentId, isStudent }: { studentId: string; isStudent: boolean }) {
  const { data, error, loading, reload } = useLoad<Page<Exercise>>(`/students/${studentId}/exercises?limit=100`);
  const tax = useTaxonomy();

  return (
    <section>
      <ActionButton
        className="primary"
        onClick={async () => {
          await post(`/students/${studentId}/exercises`, { count: 5 });
          await reload();
        }}
      >
        New exercises for the top priority
      </ActionButton>
      {loading && <Loading />}
      <ErrorBox error={error} />
      {data && data.items.length === 0 && <Empty>No exercises yet.</Empty>}
      {data && data.items.length > 0 && (
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
            {data.items.map((ex) => (
              <tr key={ex.id}>
                <td>{skillLabel(tax, ex.skill_code, ex.subskill_code)}</td>
                <td>{ex.purpose === "review" ? "From your mistakes" : "Practice"}</td>
                <td>{ex.difficulty ?? "–"}</td>
                <td>
                  <Badge kind={ex.status === "solved" ? "ok" : ex.status === "open" ? "" : "warn"}>{ex.status}</Badge>
                </td>
                <td>
                  <Link to={`/exercises/${ex.id}`}>{isStudent && ex.status === "open" ? "Solve" : "View"}</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
