import { Chess } from "chess.js";
import { useEffect, useRef, useState } from "react";

import { LiveEngine, type EngineLine, type EngineUpdate } from "../engine";
import { fmtWhite } from "../verdict";

const MAX_DEPTH = 22;
const ENGINE_PREF = "chesscoach.engine.on";

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
export function whiteShare(line: EngineLine | undefined): number {
  if (!line) return 50;
  if (line.mate !== null) return line.mate > 0 ? 100 : 0;
  return 100 / (1 + Math.exp(-0.00368208 * (line.cp ?? 0))); // same curve as the server
}

function readPref(): boolean {
  try {
    return localStorage.getItem(ENGINE_PREF) !== "off";
  } catch {
    return true;
  }
}

/** One live Stockfish (WASM, Web Worker) shared by the eval bar and the line list. */
export function useLiveEngine(fen: string) {
  const engine = useRef<LiveEngine | null>(null);
  const [on, setOnState] = useState(readPref);
  const [update, setUpdate] = useState<EngineUpdate | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const setOn = (value: boolean) => {
    setOnState(value);
    try {
      localStorage.setItem(ENGINE_PREF, value ? "on" : "off"); // per-viewer convenience only
    } catch {
      /* storage unavailable: the toggle still works for this page */
    }
  };

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

  return { on, setOn, update, failed };
}

/** Vertical eval bar, oriented like the board (your side at the bottom). */
export function EvalBar({ line, orientation }: { line: EngineLine | undefined; orientation: "white" | "black" }) {
  const white = whiteShare(line);
  const label = line ? fmtWhite(line.cp, line.mate) : "";
  // The bar is narrow: one decimal, like other eval bars. The full value is in the tooltip.
  const short = !line ? "" : line.mate !== null ? label : `${(line.cp ?? 0) > 0 ? "+" : (line.cp ?? 0) < 0 ? "−" : ""}${Math.abs((line.cp ?? 0) / 100).toFixed(1)}`;
  return (
    <div
      className={`vbar ${orientation}`}
      role="meter"
      aria-label="White's share of the winning chances"
      aria-valuenow={Math.round(white)}
      aria-valuemin={0}
      aria-valuemax={100}
      title={label ? `${label} (+ = White better, − = Black better)` : "Live engine off"}
    >
      <div className="vbar-white" style={{ height: `${white}%` }} />
      {short && <span className={`vbar-label ${white >= 50 ? "on-white" : "on-black"}`}>{short}</span>}
    </div>
  );
}

/** Compact list of the engine's best lines for the current position. */
export function EngineLines({
  fen,
  engine,
}: {
  fen: string;
  engine: ReturnType<typeof useLiveEngine>;
}) {
  const { on, setOn, update, failed } = engine;
  return (
    <section className="card engine" aria-label="Live engine">
      <div className="card-head">
        <h2 className="card-title">Live engine</h2>
        {on && update && (
          <span className="muted small">
            depth {update.depth}
            {update.done ? "" : "…"}
          </span>
        )}
        <label className="toggle">
          <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} /> on
        </label>
      </div>
      {failed && <p className="error">Engine failed to start: {failed}</p>}
      {on && !update && <p className="muted small">Thinking…</p>}
      {on && update?.done && update.lines.length === 0 && (
        <p className="muted small">No legal moves: the game is over in this position.</p>
      )}
      {on && (
        <ol className="engine-lines">
          {update?.lines.map((l) => (
            <li key={l.multipv} data-testid="engine-line">
              <b className="engine-eval">{fmtWhite(l.cp, l.mate)}</b> {sanLine(fen, l.pv)}
            </li>
          ))}
        </ol>
      )}
      <p className="muted tiny">
        Stockfish 19 lite in your browser · + White better, − Black better · exploring only, your profile uses the
        stored analysis ·{" "}
        <a href="/engine/Copying.txt" target="_blank" rel="noreferrer">
          GPLv3
        </a>{" "}
        ·{" "}
        <a href="https://github.com/nmrugg/stockfish.js" target="_blank" rel="noreferrer">
          source
        </a>
      </p>
    </section>
  );
}
