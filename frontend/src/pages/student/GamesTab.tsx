import { useState } from "react";
import { Link } from "react-router-dom";

import { api, errorText, patch, post, type Game, type ImportReport, type Page } from "../../api";
import { ActionButton, Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { useLoad } from "../../hooks";

export function GamesTab({ studentId, canEdit }: { studentId: string; canEdit: boolean }) {
  const { data, error, loading, reload } = useLoad<Page<Game>>(`/students/${studentId}/games?limit=200`);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function upload(file: File) {
    setUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      setReport(await api<ImportReport>(`/students/${studentId}/games/import`, { method: "POST", body: form }));
      await reload();
    } catch (e) {
      setUploadError(errorText(e));
    } finally {
      setUploading(false);
    }
  }

  return (
    <section>
      {canEdit && (
        <div className="card">
          <h2>Import PGN</h2>
          <input
            type="file"
            accept=".pgn,.txt"
            disabled={uploading}
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
          />
          {uploading && <Loading what="Importing" />}
          <ErrorBox error={uploadError} />
          {report && (
            <div className="report">
              <p>
                Imported <b>{report.imported}</b> · need confirmation <b>{report.needs_mapping}</b> · duplicates{" "}
                <b>{report.duplicates}</b> · rejected <b>{report.rejected}</b>
              </p>
              {report.games
                .filter((g) => g.reason && g.status !== "duplicate")
                .map((g) => (
                  <p key={g.index} className="small muted">
                    Game {g.index + 1} ({g.white} – {g.black}): {g.reason}
                  </p>
                ))}
            </div>
          )}
        </div>
      )}
      {loading && <Loading />}
      <ErrorBox error={error} />
      {data && data.items.length === 0 && <Empty>No games yet.</Empty>}
      {data && data.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>White</th>
              <th>Black</th>
              <th>Result</th>
              <th>Student plays</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((g) => (
              <tr key={g.id}>
                <td>{g.played_at ?? "–"}</td>
                <td>{g.white_name}</td>
                <td>{g.black_name}</td>
                <td>{g.result}</td>
                <td>
                  {g.student_color ? (
                    g.student_color
                  ) : canEdit ? (
                    <span className="row">
                      <Badge kind="warn">{g.mapping_status}</Badge>
                      {(["white", "black"] as const).map((c) => (
                        <ActionButton
                          key={c}
                          onClick={async () => {
                            await patch(`/games/${g.id}/mapping`, { student_color: c });
                            await reload();
                          }}
                        >
                          {c}
                        </ActionButton>
                      ))}
                    </span>
                  ) : (
                    <Badge kind="warn">unconfirmed</Badge>
                  )}
                </td>
                <td className="row">
                  {g.student_color && <Link to={`/games/${g.id}`}>View</Link>}
                  {canEdit && g.student_color && (
                    <ActionButton onClick={() => post(`/games/${g.id}/analyze`)}>Analyze</ActionButton>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
