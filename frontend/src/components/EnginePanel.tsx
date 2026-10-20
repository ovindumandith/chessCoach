import { Chess } from "chess.js";
import { useEffect, useRef, useState } from "react";

import { LiveEngine, type EngineLine, type EngineUpdate } from "../engine";
import { fmtWhite } from "../verdict";

const MAX_DEPTH = 22;

function sanLine(fen: string, uci: string[], max = 8): string {
  const chess = new Chess(fen);
  const out: string[] = [];
  for (const m of uci.slice(0, max)) {
    try {
      const move = chess.move({ from: m.slice(0, 2), to: m.slice(2, 4), promotion: m[4] });
      out.push(move.san);
    } catch {
      break; // never show an illegal continuation
    }
  }
  return out.join(" ");
}

/** White's share of the winning chances (0-100), standard eval-bar convention. */
function whiteShare(line: EngineLine | undefined): number {
  if (!line) return 50;
  if (line.mate !== null) return line.mate > 0 ? 100 : 0;
  return 100 / (1 + Math.exp(-0.00368208 * (line.cp ?? 0))); // same curve as the server
}

export function EnginePanel({ fen, pov }: { fen: string; pov: "white" | "black" }) {
  const engine = useRef<LiveEngine | null>(null);
  const [on, setOn] = useState(true);
  const [update, setUpdate] = useState<EngineUpdate | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    if (!on) return;
    try {
      engine.current = new LiveEngine(3);
      engine.current.onUpdate(setUpdate);
    } catch (e) {
      setFailed(String(e));
    }
    return () => {
      engine.current?.terminate();
      engine.current = null;
      setUpdate(null);
    };
  }, [on]);

  useEffect(() => {
    if (!on || !engine.current) return;
    setUpdate(null);
    void engine.current.analyse(fen, MAX_DEPTH);
  }, [fen, on]);

  const best = update?.lines[0];
  return (
    <section className="card engine" aria-label="Live engine">
      <div className="row">
        <strong>Live engine</strong>
        <label className="toggle">
          <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} /> on
        </label>
        {on && update && (
          <span className="muted small">
            depth {update.depth}
            {update.done ? "" : "…"}
          </span>
        )}
      </div>
      {failed && <p className="error">Engine failed to start: {failed}</p>}
      {on && (
        <>
          <div className="evalbar-wrap">
            <span className="small">White{pov === "white" ? " (you)" : ""}</span>
            <div
              className="evalbar"
              role="meter"
              aria-label="White's share of the winning chances"
              aria-valuenow={Math.round(whiteShare(best))}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div className="evalbar-fill" style={{ width: `${whiteShare(best)}%` }} />
            </div>
            <span className="small">Black{pov === "black" ? " (you)" : ""}</span>
          </div>
          {!update && <p className="muted small">Thinking…</p>}
          {update?.done && update.lines.length === 0 && (
            <p className="muted small">No legal moves: the game is over in this position.</p>
          )}
          <ol className="engine-lines">
            {update?.lines.map((l) => (
              <li key={l.multipv} data-testid="engine-line">
                <b className="engine-eval">{fmtWhite(l.cp, l.mate)}</b> {sanLine(fen, l.pv)}
              </li>
            ))}
          </ol>
        </>
      )}
      <p className="muted small">
        Stockfish 19 lite, running in your browser. + means White is better, − means Black is better
        (−9.49 = Black is ahead by about 9.5 pawns). For exploring only: your profile uses the stored server analysis. Engine licence:{" "}
        <a href="/engine/Copying.txt" target="_blank" rel="noreferrer">
          GPLv3
        </a>
        , source{" "}
        <a href="https://github.com/nmrugg/stockfish.js" target="_blank" rel="noreferrer">
          stockfish.js
        </a>
        .
      </p>
    </section>
  );
}
