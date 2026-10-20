import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorText, patch, post, type Game, type ImportReport, type Page } from "../../api";
import { AnalysisBadge, IN_PROGRESS } from "../../components/AnalysisBadge";
import { ActionButton, Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { useLoad, usePoll } from "../../hooks";

/**
 * The student's games. The student adds games (PGN), confirms which side they played and
 * queues analysis; the coach sees the same list read-only. The server enforces the same rules.
 */
export function GamesTab({
  studentId,
  viewer,
  onChange,
}: {
  studentId: string;
  viewer: "coach" | "student";
  /** Called when games are added or finish analysis (e.g. to update a summary elsewhere). */
  onChange?: () => void;
}) {
  const isStudent = viewer === "student";
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
  const signature = data ? `${games.length}:${games.filter((g) => g.analysis_status === "analyzed").length}` : null;
  const notify = useRef(onChange);
  notify.current = onChange;
  const lastSignature = useRef<string | null>(null);
  useEffect(() => {
    if (signature === null) return;
    if (lastSignature.current !== null && lastSignature.current !== signature) notify.current?.();
    lastSignature.current = signature;
  }, [signature]);

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
      {!isStudent && (
        <p className="muted small">
          Your student adds and analyzes their own games. You see them here as they come in; open a game to see its
          analysis, and see the mistakes found in the <i>Mistakes</i> tab.
        </p>
      )}
      {isStudent && (
        <div className="card">
          <h2>Add your games</h2>
          <p className="muted small">
            Upload a .pgn file, for example an export from Lichess or Chess.com, then analyze it. The mistakes found
            appear in <i>My mistakes</i>. Your coach can see your games too.
          </p>
          <input
            aria-label="PGN file"
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
      {games.length > 0 && (
        <div className="row">
          {isStudent && (
            <ActionButton
              className="primary"
              disabled={toAnalyze.length === 0}
              onClick={() => analyze(toAnalyze.map((g) => g.id))}
            >
              Analyze all ({toAnalyze.length})
            </ActionButton>
          )}
          {inProgress > 0 && (
            <span className="muted small">
              Stockfish is working on {inProgress} game{inProgress > 1 ? "s" : ""}; this list updates by itself.
            </span>
          )}
        </div>
      )}
      {loading && <Loading />}
      <ErrorBox error={error} />
      {data && games.length === 0 && (
        <Empty>
          {isStudent ? "No games yet. Add a PGN file above to get started." : "Your student has not added any games yet."}
        </Empty>
      )}
      {!isStudent && games.some((g) => g.added_by === "student") && (
        <p className="muted small" data-testid="student-added">
          {games.filter((g) => g.added_by === "student").length} of {games.length} games were added by the student
          (marked <Badge kind="ok">student</Badge>).
        </p>
      )}
      {games.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>White</th>
              <th>Black</th>
              <th>Result</th>
              <th>{isStudent ? "You played" : "Student plays"}</th>
              <th>Analysis</th>
              <th>Added by</th>
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
                  ) : !isStudent ? (
                    <Badge kind="warn">not confirmed yet</Badge>
                  ) : (
                    <span className="row" title="Which side were you?">
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
                  )}
                </td>
                <td>{g.student_color ? <AnalysisBadge state={g.analysis_status} /> : "–"}</td>
                <td>
                  {g.added_by === "student" ? (
                    <Badge kind={isStudent ? undefined : "ok"}>{isStudent ? "you" : "student"}</Badge>
                  ) : g.added_by === "coach" ? (
                    <span className="muted small">coach</span>
                  ) : (
                    <span className="muted small">–</span>
                  )}
                </td>
                <td>
                  <span className="row">
                    {g.student_color && <Link to={`/games/${g.id}`}>View</Link>}
                    {isStudent &&
                      g.student_color &&
                      (g.analysis_status === "not_requested" || g.analysis_status === "failed") && (
                        <ActionButton onClick={() => analyze([g.id])}>
                          {g.analysis_status === "failed" ? "Retry" : "Analyze"}
                        </ActionButton>
                      )}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
