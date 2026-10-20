import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { formatEval, post, type Game, type GameAnalysis, type MoveAnalysis } from "../api";
import { Board } from "../components/Board";
import { ActionButton, Badge, ErrorBox, Loading, pct } from "../components/ui";
import { useLoad } from "../hooks";

/** One game: every student move with the engine's verdict, shown on the board. */
export function GameViewer() {
  const { id = "" } = useParams();
  const game = useLoad<Game>(`/games/${id}`);
  const analysis = useLoad<GameAnalysis>(`/games/${id}/analysis`);
  const [ply, setPly] = useState<number | null>(null);

  // Deeper critical-pass rows replace their baseline plies.
  const moves = useMemo<MoveAnalysis[]>(() => {
    if (!analysis.data) return [];
    const byPly = new Map(analysis.data.moves.map((m) => [m.ply, m]));
    analysis.data.critical_moves.forEach((m) => byPly.set(m.ply, m));
    return [...byPly.values()].sort((a, b) => a.ply - b.ply);
  }, [analysis.data]);
  const current = moves.find((m) => m.ply === ply) ?? moves[0];
  const g = game.data;

  return (
    <main>
      {(game.loading || analysis.loading) && <Loading />}
      <ErrorBox error={game.error} />
      {g && (
        <h1>
          {g.white_name} – {g.black_name} <span className="muted">{g.result}</span>
        </h1>
      )}
      {analysis.error && (
        <div className="card">
          <p>{analysis.error}</p>
          <ActionButton
            onClick={async () => {
              await post(`/games/${id}/analyze`);
              await analysis.reload();
            }}
          >
            Analyze this game
          </ActionButton>
          <button onClick={() => void analysis.reload()}>Check again</button>
        </div>
      )}
      {analysis.data && current && (
        <div className="viewer">
          <div>
            <Board
              fen={current.fen_before}
              orientation={analysis.data.student_color ?? "white"}
              bestMove={current.best_move_uci !== current.uci_move ? current.best_move_uci : null}
              playedMove={current.uci_move}
              size={420}
            />
            <p className="small">
              <span className="legend red" /> played <span className="legend green" /> engine best
            </p>
            <div className="card">
              <p>
                Move {Math.ceil(current.ply / 2)}: <b>{current.san_move}</b> ·{" "}
                {formatEval(current.eval_before_cp, current.eval_before_mate)} →{" "}
                {formatEval(current.eval_after_cp, current.eval_after_mate, true)}
              </p>
              {current.features.pv_san?.length ? <p>Engine line: {current.features.pv_san.slice(0, 8).join(" ")}</p> : null}
              {current.features.refutation_san?.length ? (
                <p>Opponent's best reply: {current.features.refutation_san.slice(0, 4).join(" ")}</p>
              ) : null}
              <p className="muted small">
                {analysis.data.baseline.engine_name} {analysis.data.baseline.engine_version}, depth{" "}
                {String(analysis.data.baseline.configuration.depth ?? "?")}
                {analysis.data.critical && " (critical moves re-checked deeper)"}
              </p>
            </div>
          </div>
          <ol className="moves">
            {moves.map((m) => (
              <li key={m.ply}>
                <button className={`move ${m.ply === current.ply ? "active" : ""}`} onClick={() => setPly(m.ply)}>
                  {Math.ceil(m.ply / 2)}. {m.san_move}
                  <span className="muted"> {formatEval(m.eval_after_cp, m.eval_after_mate, true)}</span>
                  {(m.win_prob_loss ?? 0) >= 0.1 && <Badge kind="warn">−{pct(m.win_prob_loss)}</Badge>}
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}
    </main>
  );
}
