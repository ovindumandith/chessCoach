import { Link } from "react-router-dom";

import { skillLabel } from "../api";
import { Badge, Empty, ErrorBox, Loading } from "../components/ui";
import { useLoad, useTaxonomy } from "../hooks";

interface Group {
  skill_code: string;
  subskill_code: string | null;
  findings: number;
  acknowledged: number;
  open: number;
  students: { student_id: string; display_name: string; findings: number }[];
  examples: {
    student_id: string;
    display_name: string;
    game_id: string;
    ply: number;
    move_number: number;
    san: string;
    played_at: string | null;
    acknowledged: boolean;
  }[];
}

interface Overview {
  students_total: number;
  students_with_findings: number;
  groups: Group[];
}

/** Coach view: which mistakes their students make, across all of them. Read-only. */
export function Mistakes() {
  const { data, error, loading } = useLoad<Overview>("/cohort/mistakes");
  const tax = useTaxonomy();

  return (
    <main>
      <h1>Mistakes across your students</h1>
      <p className="muted">
        Built from the games your students added and analyzed. Mistakes made by the most students come first. Open a
        student to see their mistakes game by game.
      </p>
      {loading && <Loading />}
      <ErrorBox error={error} />
      {data && data.groups.length === 0 && (
        <Empty>No findings yet. They appear once your students add and analyze games.</Empty>
      )}
      {data && data.groups.length > 0 && (
        <>
          <p className="small">
            {data.students_with_findings} of {data.students_total} students have findings.
          </p>
          <table className="mistakes">
            <thead>
              <tr>
                <th>Mistake</th>
                <th>Students</th>
                <th>Findings</th>
                <th>Recent examples</th>
              </tr>
            </thead>
            <tbody>
              {data.groups.map((g) => (
                <tr key={`${g.skill_code}/${g.subskill_code}`}>
                  <td>
                    <b>{skillLabel(tax, g.skill_code, g.subskill_code)}</b>
                  </td>
                  <td>
                    <b>
                      {g.students.length} of {data.students_total}
                    </b>
                    <div className="small muted">
                      {g.students.map((s, i) => (
                        <span key={s.student_id}>
                          {i > 0 && ", "}
                          <Link to={`/students/${s.student_id}?tab=mistakes`}>{s.display_name}</Link> ({s.findings})
                        </span>
                      ))}
                    </div>
                  </td>
                  <td>
                    {g.findings}
                    <div className="small">
                      {g.acknowledged > 0 && <Badge kind="ok">{g.acknowledged} acknowledged</Badge>}{" "}
                      {g.open > 0 && <Badge>{g.open} not yet</Badge>}
                    </div>
                  </td>
                  <td>
                    <ul className="examples">
                      {g.examples.map((e) => (
                        <li key={`${e.game_id}/${e.ply}`}>
                          <Link to={`/games/${e.game_id}?ply=${e.ply}`}>
                            {e.move_number}
                            {e.ply % 2 ? "." : "…"} {e.san}
                          </Link>{" "}
                          <span className="muted small">
                            {e.display_name}
                            {e.played_at && `, ${e.played_at}`}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
