import { post, skillLabel, type Profile } from "../../api";
import { ActionButton, Badge, Empty, ErrorBox, Loading, pct, STATE_LABEL } from "../../components/ui";
import { useLoad, useTaxonomy } from "../../hooks";

export function ProfileTab({ studentId, canRebuild }: { studentId: string; canRebuild: boolean }) {
  const { data, error, loading, reload, setData } = useLoad<Profile>(`/students/${studentId}/profile`);
  const tax = useTaxonomy();
  const withEvidence = data?.skills.filter((s) => s.error_count > 0 || s.state === "no_issue_detected") ?? [];

  return (
    <section>
      {canRebuild && (
        <div className="row">
          <ActionButton onClick={async () => setData(await post<Profile>(`/students/${studentId}/profile/rebuild`))}>
            Rebuild profile
          </ActionButton>
          {data?.stale && <Badge kind="warn">New evidence since this version</Badge>}
        </div>
      )}
      {loading && <Loading />}
      {error && !data && (error.includes("No profile") ? <Empty>No profile yet. Analyze some games first.</Empty> : <ErrorBox error={error} />)}
      {data && (
        <>
          <p className="muted small">
            Version {data.snapshot.profile_version} · {data.snapshot.summary.games_included} games ·{" "}
            {data.snapshot.summary.moves_analyzed} moves analyzed. Priority is a training heuristic, not a measure of
            ability.
          </p>
          {withEvidence.length === 0 && <Empty>No findings yet.</Empty>}
          {withEvidence.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Skill</th>
                  <th>State</th>
                  <th>Errors</th>
                  <th>Games</th>
                  <th>Rate</th>
                  <th>Priority</th>
                  <th>Exercises</th>
                </tr>
              </thead>
              <tbody>
                {withEvidence.map((s) => (
                  <tr key={`${s.skill_code}.${s.subskill_code}`}>
                    <td>
                      {skillLabel(tax, s.skill_code, s.subskill_code)}
                      {s.evidence_summary.provisional && <Badge kind="warn">mostly unreviewed</Badge>}
                    </td>
                    <td>{STATE_LABEL[s.state] ?? s.state}</td>
                    <td>{s.error_count}</td>
                    <td>{s.games_affected}</td>
                    <td title={`${s.opportunity_count ?? "?"} opportunities`}>{pct(s.error_rate, 1)}</td>
                    <td>{s.priority_score === null ? <span className="muted">review queue</span> : s.priority_score.toFixed(3)}</td>
                    <td>
                      {s.evidence_summary.exercises?.attempted
                        ? `${pct(s.evidence_summary.exercises.first_try_accuracy)} of ${s.evidence_summary.exercises.attempted}`
                        : "–"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {canRebuild && (
            <p className="small">
              <button onClick={() => void reload()}>Refresh</button>
            </p>
          )}
        </>
      )}
    </section>
  );
}
