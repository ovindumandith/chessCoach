import { useState } from "react";
import { Link } from "react-router-dom";

import { api, errorText, patch, post, type Game, type ImportReport, type Page } from "../../api";
import { AnalysisBadge, IN_PROGRESS } from "../../components/AnalysisBadge";
import { ActionButton, Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { useLoad, usePoll } from "../../hooks";

export function GamesTab({ studentId, canEdit }: { studentId: string; canEdit: boolean }) {
  const { data, error, loading, reload, refresh } = useLoad<Page<Game>>(`/students/${studentId}/games?limit=200`);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const games = data?.items ?? [];
  const inProgress = games.filter((g) => g.analysis_status && IN_PROGRESS.includes(g.analysis_status)).length;
  const toAnalyze = games.filter(
    (g) => g.student_color && (g.analysis_status === "not_requested" || g.analysis_status === "failed"),
  );
  // Follow running analyses live; stop polling when nothing is in progress.
  usePoll(refresh, 4000, inProgress > 0);

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

  async function analyze(gameIds: string[]) {
    for (const id of gameIds) await post(`/games/${id}/analyze`);
    await refresh();
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
      {canEdit && games.length > 0 && (
        <div className="row">
          <ActionButton
            className="primary"
            disabled={toAnalyze.length === 0}
            onClick={() => analyze(toAnalyze.map((g) => g.id))}
          >
            Analyze all ({toAnalyze.length})
          </ActionButton>
          {inProgress > 0 && (
            <span className="muted small">
              Stockfish is working on {inProgress} game{inProgress > 1 ? "s" : ""}; this list updates by itself.
            </span>
          )}
        </div>
      )}
      {loading && <Loading />}
      <ErrorBox error={error} />
      {data && games.length === 0 && <Empty>No games yet.</Empty>}
      {games.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>White</th>
              <th>Black</th>
              <th>Result</th>
              <th>Student plays</th>
              <th>Analysis</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {games.map((g) => (
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
                <td>{g.student_color ? <AnalysisBadge state={g.analysis_status} /> : "–"}</td>
                <td className="row">
                  {g.student_color && <Link to={`/games/${g.id}`}>View</Link>}
                  {canEdit &&
                    g.student_color &&
                    (g.analysis_status === "not_requested" || g.analysis_status === "failed") && (
                      <ActionButton onClick={() => analyze([g.id])}>
                        {g.analysis_status === "failed" ? "Retry" : "Analyze"}
                      </ActionButton>
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
