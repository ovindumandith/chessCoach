import { Chess, type Move } from "chess.js";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { post, skillLabel, type Annotation, type AnalysisStatus, type GameAnnotations, type GameDetail } from "../api";
import { IN_PROGRESS } from "../components/AnalysisBadge";
import { Board } from "../components/Board";
import { EnginePanel } from "../components/EnginePanel";
import { EvalGraph, type GraphPoint } from "../components/EvalGraph";
import { ActionButton, Badge, ErrorBox, Loading } from "../components/ui";
import { useLoad, usePoll, useTaxonomy } from "../hooks";
import { describeWhite, fmtWhite, type Side } from "../verdict";

interface SameMistake {
  game_id: string;
  ply: number;
  move_number: number;
  san_move: string;
  played_at: string | null;
  opponent: string;
  earlier: boolean;
}

interface Finding {
  observation_id: string;
  ply: number;
  skill_code: string;
  subskill_code: string | null;
  motif_kind: string | null;
  same_mistake_count: number;
  same_mistake_elsewhere: SameMistake[];
}

const KIND_TEXT: Record<string, string> = { missed: "you missed it", allowed: "you allowed it" };
const MISTAKES = new Set(["inaccuracy", "mistake", "blunder"]);
const NAME: Record<Side, string> = { white: "White", black: "Black" };

function parseGame(pgn: string | undefined): { moves: Move[]; error: string | null } {
  if (!pgn) return { moves: [], error: null };
  try {
    const chess = new Chess();
    chess.loadPgn(pgn);
    return { moves: chess.history({ verbose: true }), error: null };
  } catch (e) {
    return { moves: [], error: `Could not read the game's moves: ${String(e)}` };
  }
}

const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));

const moveLabel = (ply: number, san: string) => `${Math.ceil(ply / 2)}${ply % 2 ? "." : "…"} ${san}`;

/** The original game on the left, the annotation of the current move (either side) on the right.
 * Keyboard: ↓/→ next move, ↑/← previous, Home/End, N/P next/previous key moment, Esc stops exploring. */
export function GameViewer() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const game = useLoad<GameDetail>(`/games/${id}`);
  const status = useLoad<AnalysisStatus>(`/games/${id}/analysis-status`);
  const state = status.data?.state;
  const ready = Boolean(status.data?.results_available);
  usePoll(status.refresh, 3000, Boolean(state && IN_PROGRESS.includes(state)));
  const notes = useLoad<GameAnnotations>(ready ? `/games/${id}/annotations` : null);
  const findings = useLoad<{ findings: Finding[] }>(ready ? `/games/${id}/findings` : null);
  const lastState = useRef(state);
  useEffect(() => {
    if (lastState.current === "deepening" && state === "analyzed") {
      void notes.refresh();
      void findings.refresh();
    }
    lastState.current = state;
  }, [state, notes, findings]);
  const tax = useTaxonomy();

  const { moves, error: parseError } = useMemo(() => parseGame(game.data?.raw_pgn), [game.data?.raw_pgn]);
  const total = moves.length;
  const student: Side = game.data?.student_color ?? "white";

  const byPly = useMemo(() => {
    const map = new Map<number, Annotation>();
    notes.data?.annotations.forEach((a) => map.set(a.ply, a));
    return map;
  }, [notes.data]);
  const findingsByPly = useMemo(() => {
    const map = new Map<number, Finding[]>();
    for (const f of findings.data?.findings ?? []) {
      if (f.skill_code !== "unclassified") map.set(f.ply, [...(map.get(f.ply) ?? []), f]);
    }
    return map;
  }, [findings.data]);
  const keyMoments = useMemo(
    () => [...byPly.values()].filter((a) => MISTAKES.has(a.verdict)).map((a) => a.ply).sort((a, b) => a - b),
    [byPly],
  );

  // Position: ply 0 = start, ply N = after the N-th half-move.
  const requested = Number(params.get("ply") ?? 0);
  const ply = Number.isFinite(requested) ? Math.max(0, Math.min(total, requested)) : 0;
  const [explore, setExplore] = useState<{ fen: string; moves: string[] } | null>(null);
  const plyRef = useRef(ply); // source of truth between renders: fast key presses never lose a step
  plyRef.current = ply;
  const go = useCallback(
    (next: number) => {
      const clamped = Math.max(0, Math.min(total, next));
      plyRef.current = clamped;
      setExplore(null);
      setParams({ ply: String(clamped) }, { replace: true });
    },
    [setParams, total],
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (isTyping(e.target) || e.altKey || e.ctrlKey || e.metaKey) return;
      const now = plyRef.current;
      const next = keyMoments.find((p) => p > now);
      const prev = [...keyMoments].reverse().find((p) => p < now);
      const actions: Record<string, () => void> = {
        ArrowDown: () => go(now + 1),
        ArrowRight: () => go(now + 1),
        ArrowUp: () => go(now - 1),
        ArrowLeft: () => go(now - 1),
        Home: () => go(0),
        End: () => go(total),
        n: () => next !== undefined && go(next),
        p: () => prev !== undefined && go(prev),
        Escape: () => setExplore(null),
      };
      const action = actions[e.key] ?? actions[e.key.toLowerCase()];
      if (action) {
        e.preventDefault();
        action();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, total, keyMoments]);

  const move = ply > 0 ? moves[ply - 1] : null;
  const gameFen = move ? move.after : (moves[0]?.before ?? new Chess().fen());
  const shownFen = explore?.fen ?? gameFen;
  const note = move ? byPly.get(ply) : undefined;
  const isMistake = Boolean(note && MISTAKES.has(note.verdict));
  const showBest = !explore && note && note.verdict !== "best" && note.verdict !== "good";

  function exploreMove(uci: string) {
    const chess = new Chess(shownFen);
    const m = chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    setExplore({ fen: chess.fen(), moves: [...(explore?.moves ?? []), m.san] });
  }

  const graph: GraphPoint[] = useMemo(() => {
    const points: GraphPoint[] = [];
    for (let p = 1; p <= total; p++) {
      const w = notes.data?.win_chance_white[String(p)];
      const value = w === undefined || w === null ? null : student === "white" ? w : 1 - w;
      const a = byPly.get(p);
      points.push({ ply: p, value, mark: a?.verdict, opponent: a?.side === "opponent" });
    }
    return points;
  }, [notes.data, byPly, total, student]);

  const g = game.data;
  return (
    <main className="game-page">
      {game.loading && <Loading />}
      <ErrorBox error={game.error ?? parseError} />
      {g && <GameHeader g={g} />}
      {g && <StatusBanner status={status.data} gameId={id} onQueued={status.refresh} />}
      {keyMoments.length > 0 && (
        <nav className="key-moments" aria-label="Key moments">
          <span className="muted small">Key moments:</span>
          {keyMoments.map((p) => {
            const a = byPly.get(p)!;
            return (
              <button
                key={p}
                className={`chip ${a.verdict} ${a.side}`}
                onClick={() => go(p)}
                aria-current={p === ply}
                title={`${a.side === "student" ? "Your" : "Your opponent's"} ${a.label.toLowerCase()}`}
              >
                <span className="chip-side">{a.side === "student" ? "You" : "Opp"}</span> {moveLabel(p, a.san)}{" "}
                {a.symbol}
              </button>
            );
          })}
        </nav>
      )}
      {g && (
        <div className="analysis-layout">
          <section aria-label="Original game">
            <Board
              fen={shownFen}
              orientation={student}
              onMove={exploreMove}
              lastMove={explore ? null : move?.lan}
              bestMove={showBest ? note.best_move_uci : null}
              threat={!explore && isMistake ? note?.threat_uci : null}
              size={460}
            />
            <div className="nav-buttons" role="group" aria-label="Move navigation">
              <button onClick={() => go(0)} title="Start (Home)" aria-label="Start">⏮</button>
              <button onClick={() => go(ply - 1)} title="Previous move (↑ or ←)" aria-label="Previous move">◀</button>
              <span className="muted small ply-counter">
                {ply === 0 ? "Start" : `Move ${Math.ceil(ply / 2)}${ply % 2 ? "" : "…"}`} · {ply}/{total}
              </span>
              <button onClick={() => go(ply + 1)} title="Next move (↓ or →)" aria-label="Next move">▶</button>
              <button onClick={() => go(total)} title="End (End)" aria-label="End">⏭</button>
            </div>
            <p className="muted small keys-hint">
              Keys: <kbd>↓</kbd>/<kbd>→</kbd> next · <kbd>↑</kbd>/<kbd>←</kbd> back · <kbd>N</kbd>/<kbd>P</kbd> next/previous
              key moment · drag a piece to explore
            </p>
            {explore && (
              <p className="row small exploring">
                <Badge kind="warn">Exploring</Badge> {explore.moves.join(" ")}
                <button onClick={() => setExplore(null)}>Back to the game (Esc)</button>
              </p>
            )}
            {ready && <EvalGraph points={graph} totalPlies={total} currentPly={ply} onSelect={go} you={student} />}
            <EnginePanel fen={shownFen} pov={student} />
          </section>
          <section aria-label="Analysis of this move">
            <MovePanel
              student={student}
              ply={ply}
              move={move}
              note={note}
              findings={findingsByPly.get(ply) ?? []}
              ready={ready}
              tax={tax}
            />
            <MoveList moves={moves} ply={ply} byPly={byPly} findingsByPly={findingsByPly} onSelect={go} />
            <Legend />
          </section>
        </div>
      )}
    </main>
  );
}

function GameHeader({ g }: { g: GameDetail }) {
  const you = (c: Side) => (g.student_color === c ? <Badge kind="ok">you</Badge> : null);
  return (
    <header className="game-header">
      <h1>
        <span className="player">
          <span className="piece-dot white" aria-hidden /> {g.white_name} {you("white")}
        </span>
        <span className="muted"> vs </span>
        <span className="player">
          <span className="piece-dot black" aria-hidden /> {g.black_name} {you("black")}
        </span>
      </h1>
      <p className="muted small">
        Result {g.result}
        {g.played_at && ` · ${g.played_at}`}
        {g.time_control && ` · time control ${g.time_control}`}
        {g.opening_eco && ` · opening ${g.opening_eco}`}
      </p>
    </header>
  );
}

function StatusBanner({
  status,
  gameId,
  onQueued,
}: {
  status: AnalysisStatus | null;
  gameId: string;
  onQueued: () => Promise<void>;
}) {
  if (!status || status.state === "analyzed") return null;
  const s = status.state;
  return (
    <div className={`card banner ${s}`} role="status">
      {s === "not_requested" && <span>This game has not been analyzed yet. You can already step through it.</span>}
      {s === "queued" && (
        <span>
          Waiting for Stockfish{status.jobs_ahead ? ` (${status.jobs_ahead} game(s) ahead)` : ""}… you can already step
          through the game.
        </span>
      )}
      {s === "running" && <span>Stockfish is analyzing your {status.moves_to_analyze} moves… this page updates by itself.</span>}
      {s === "deepening" && <span>Analysis ready. Re-checking the critical moves at higher depth…</span>}
      {s === "failed" && <span className="error">Analysis failed: {status.error_message}</span>}
      {(s === "not_requested" || s === "failed") && (
        <ActionButton
          className="primary"
          onClick={async () => {
            await post(`/games/${gameId}/analyze`);
            await onQueued();
          }}
        >
          {s === "failed" ? "Try again" : "Analyze this game"}
        </ActionButton>
      )}
    </div>
  );
}

function MovePanel({
  student,
  ply,
  move,
  note,
  findings,
  ready,
  tax,
}: {
  student: Side;
  ply: number;
  move: Move | null;
  note: Annotation | undefined;
  findings: Finding[];
  ready: boolean;
  tax: ReturnType<typeof useTaxonomy>;
}) {
  if (!move) {
    return (
      <div className="card move-panel" data-testid="move-panel">
        <h2>Start position</h2>
        <p>
          You played <b>{NAME[student]}</b> in this game.
        </p>
        <p>Step through the game with the arrow keys or the buttons under the board.</p>
        <p className="muted small">Both sides' moves are graded. Only your own moves count toward your profile.</p>
      </div>
    );
  }
  const own = (note?.side ?? (move.color === (student === "white" ? "w" : "b") ? "student" : "opponent")) === "student";
  const whose = own ? "your move" : "your opponent's move";

  if (!note) {
    return (
      <div className="card move-panel" data-testid="move-panel">
        <h2>
          {moveLabel(ply, move.san)} <span className="muted small">{whose}</span>
        </h2>
        <p className="muted">
          {ready
            ? "No analysis for this move (for example the first or last move of the game)."
            : "Stockfish has not analyzed this move yet."}
        </p>
      </div>
    );
  }

  const mistake = MISTAKES.has(note.verdict);
  return (
    <div className={`card move-panel verdict-${note.verdict}`} data-testid="move-panel">
      <h2>
        {moveLabel(ply, note.san)} {note.symbol && <span className="move-symbol">{note.symbol}</span>}{" "}
        <span className="muted small">{whose}</span>
      </h2>
      <p className={`verdict ${note.verdict}`} data-testid="verdict">
        {note.label}
      </p>
      <p>
        Before {own ? "your" : "this"} move {describeWhite(note.eval_before, student)} (
        <span className="evalnum">{fmtWhite(note.eval_before.cp, note.eval_before.mate)}</span>). After it,{" "}
        {describeWhite(note.eval_after, student, true)} (
        <span className="evalnum">{fmtWhite(note.eval_after.cp, note.eval_after.mate)}</span>).
      </p>
      {note.verdict !== "best" && note.verdict !== "good" && note.best_move_san && (
        <p>
          <span className="legend green" /> {own ? "Better was" : "Your opponent should have played"}{" "}
          <b>{note.best_move_san}</b>
          {note.best_line_san.length > 1 && <span className="muted">: {note.best_line_san.slice(0, 6).join(" ")}</span>}
        </p>
      )}
      {note.reasons.length > 0 && (
        <div className="why" data-testid="why">
          {mistake && <p className="why-title">Why</p>}
          <ul>
            {note.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      {mistake && note.threat_uci && (
        <p className="muted small">
          <span className="legend orange" /> orange arrow: {own ? "the reply your move allowed" : "how you could punish it"}
        </p>
      )}
      {own &&
        findings.map((f) => (
          <div key={f.observation_id} className="finding" data-testid="finding">
            <p>
              <b>{skillLabel(tax, f.skill_code, f.subskill_code)}</b>
              {f.motif_kind && <span className="muted"> ({KIND_TEXT[f.motif_kind] ?? f.motif_kind})</span>}
            </p>
            {f.same_mistake_count > 0 ? (
              <>
                <p className="warn">
                  You made the same mistake in {f.same_mistake_count} other game{f.same_mistake_count > 1 ? "s" : ""}:
                </p>
                <ul className="same-mistakes">
                  {f.same_mistake_elsewhere.map((s) => (
                    <li key={`${s.game_id}-${s.ply}`}>
                      <Link to={`/games/${s.game_id}?ply=${s.ply}`}>
                        vs {s.opponent}
                        {s.played_at ? `, ${s.played_at}` : ""}, move {s.move_number}: {s.san_move}
                      </Link>{" "}
                      <span className="muted small">{s.earlier ? "(earlier)" : "(later)"}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="muted small">Not seen in your other analyzed games.</p>
            )}
          </div>
        ))}
    </div>
  );
}

function MoveList({
  moves,
  ply,
  byPly,
  findingsByPly,
  onSelect,
}: {
  moves: Move[];
  ply: number;
  byPly: Map<number, Annotation>;
  findingsByPly: Map<number, Finding[]>;
  onSelect: (ply: number) => void;
}) {
  const active = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    active.current?.scrollIntoView({ block: "nearest" });
  }, [ply]);

  const rows = [];
  for (let i = 0; i < moves.length; i += 2) rows.push(i);
  const cell = (p: number) => {
    const m = moves[p - 1];
    if (!m) return <td />;
    const a = byPly.get(p);
    const repeated = findingsByPly.get(p)?.some((f) => f.same_mistake_count > 0);
    return (
      <td>
        <button
          ref={p === ply ? active : undefined}
          className={`mv ${a?.verdict ?? ""} ${a?.side ?? ""} ${p === ply ? "active" : ""}`}
          onClick={() => onSelect(p)}
          aria-current={p === ply}
          title={a ? `${a.label} (${a.side === "student" ? "you" : "opponent"})` : undefined}
        >
          {m.san}
          {a?.symbol && <span className="move-symbol">{a.symbol}</span>}
          {repeated && <span className="repeat" title="You made this mistake before">↻</span>}
        </button>
      </td>
    );
  };
  return (
    <div className="movelist" role="region" aria-label="Moves">
      <table>
        <tbody>
          {rows.map((i) => (
            <tr key={i}>
              <th scope="row">{i / 2 + 1}.</th>
              {cell(i + 1)}
              {cell(i + 2)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Legend() {
  return (
    <details className="legend-box">
      <summary>How to read this</summary>
      <ul className="small">
        <li>
          <span className="move-symbol">??</span> blunder · <span className="move-symbol">?</span> mistake ·{" "}
          <span className="move-symbol">?!</span> inaccuracy · <span className="move-symbol">✓</span> the engine's best move.
          Both sides are graded; only your moves count toward your profile.
        </li>
        <li>
          Numbers use chess notation: <b>+</b> means White is better, <b>−</b> means Black is better (+1.00 ≈ a pawn).{" "}
          <b>#3</b> = White mates in 3, <b>#−3</b> = Black mates in 3.
        </li>
        <li>
          <span className="legend green" /> green arrow: the better move · <span className="legend orange" /> orange
          arrow: what the mistake allowed · yellow squares: the move just played.
        </li>
        <li>"Why" is worked out from the engine's line on the board: mates, material won or lost, forks.</li>
        <li>↻ marks a mistake you have made in other games too. The graph shows your winning chances; click to jump.</li>
      </ul>
    </details>
  );
}
