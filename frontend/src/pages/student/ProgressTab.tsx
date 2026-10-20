import { skillLabel, type ProgressSkill } from "../../api";
import { Empty, ErrorBox, Loading, pct, STATE_LABEL } from "../../components/ui";
import { useLoad, useTaxonomy } from "../../hooks";

export function ProgressTab({ studentId }: { studentId: string }) {
  const { data, error, loading } = useLoad<{ note: string; skills: ProgressSkill[] }>(`/students/${studentId}/progress`);
  const tax = useTaxonomy();
  const skills = data?.skills.filter((s) => s.skill_code !== "unclassified") ?? [];

  return (
    <section>
      {loading && <Loading />}
      <ErrorBox error={error} />
      {data && <p className="muted small">{data.note}</p>}
      {data && skills.length === 0 && <Empty>No progress data yet.</Empty>}
      {skills.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Skill</th>
              <th>Exercises (first try)</th>
              <th>Game evidence over time</th>
            </tr>
          </thead>
          <tbody>
            {skills.map((s) => {
              const last = s.profile_trend[s.profile_trend.length - 1];
              const first = s.profile_trend[0];
              return (
                <tr key={`${s.skill_code}.${s.subskill_code}`}>
                  <td>{skillLabel(tax, s.skill_code, s.subskill_code)}</td>
                  <td>
                    {s.exercises.attempted
                      ? `${s.exercises.solved_first_try}/${s.exercises.attempted} (${pct(s.exercises.first_try_accuracy)})`
                      : "–"}
                  </td>
                  <td>
                    {last
                      ? `${STATE_LABEL[last.state] ?? last.state}, ${last.games_affected} game(s)` +
                        (first && first !== last ? ` (v${first.profile_version} → v${last.profile_version})` : "")
                      : "–"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
