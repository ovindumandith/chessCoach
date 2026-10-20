import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { errorText, post, type Page, type Student } from "../api";
import { Badge, Empty, ErrorBox, Loading } from "../components/ui";
import { useLoad } from "../hooks";

export function Students() {
  const { data, error, loading, reload } = useLoad<Page<Student>>("/students?limit=200");
  const [name, setName] = useState("");
  const [aliases, setAliases] = useState("");
  const [level, setLevel] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  async function create(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    try {
      await post("/students", {
        display_name: name,
        aliases: aliases.split(",").map((a) => a.trim()).filter(Boolean),
        skill_level: level || null,
      });
      setName("");
      setAliases("");
      setLevel("");
      await reload();
    } catch (err) {
      setFormError(errorText(err));
    }
  }

  return (
    <main>
      <h1>Students</h1>
      {loading && <Loading />}
      <ErrorBox error={error} />
      {data && data.items.length === 0 && <Empty>No students yet. Add your first student below.</Empty>}
      {data && data.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>PGN names</th>
              <th>Level</th>
              <th>Games</th>
              <th>Added by the student</th>
              <th>Open mistakes</th>
              <th>Student login</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((s) => (
              <tr key={s.id}>
                <td>
                  <Link to={`/students/${s.id}`}>{s.display_name}</Link>
                </td>
                <td>{s.aliases.join(", ") || <span className="muted">none</span>}</td>
                <td>{s.skill_level ?? "–"}</td>
                <td>{s.activity?.games ?? "–"}</td>
                <td>
                  {s.activity?.games_by_student ? (
                    <span className="row">
                      <Badge kind="ok">{s.activity.games_by_student}</Badge>
                      {s.activity.last_student_upload && (
                        <span className="muted small">latest {s.activity.last_student_upload.slice(0, 10)}</span>
                      )}
                    </span>
                  ) : (
                    <span className="muted">–</span>
                  )}
                </td>
                <td>
                  {s.activity?.mistakes ? (
                    <Link to={`/students/${s.id}?tab=mistakes`} title="Mistakes the student has not acknowledged yet">
                      <Badge kind={s.activity.open_mistakes ? "warn" : "ok"}>
                        {s.activity.open_mistakes} of {s.activity.mistakes}
                      </Badge>
                    </Link>
                  ) : (
                    <span className="muted">–</span>
                  )}
                </td>
                <td>
                  {s.activity?.has_login ? (
                    "yes"
                  ) : (
                    <Link to={`/students/${s.id}?tab=account`} className="small">
                      create one
                    </Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form onSubmit={create} className="card inline-form">
        <h2>Add student</h2>
        <label>
          Display name
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>
          PGN player names (comma separated)
          <input value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="Ovindu, ovindu_m" />
        </label>
        <label>
          Level
          <input value={level} onChange={(e) => setLevel(e.target.value)} placeholder="club" />
        </label>
        <ErrorBox error={formError} />
        <button type="submit" className="primary">
          Add student
        </button>
      </form>
    </main>
  );
}
