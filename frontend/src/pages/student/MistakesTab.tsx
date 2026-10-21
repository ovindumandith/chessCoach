import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  del,
  post,
  put,
  skillLabel,
  type GameMistakes,
  type Mistake,
  type MistakesPage,
  type PuzzleSet,
  type PuzzleSetList,
} from "../../api";
import { ActionButton, Badge, Empty, ErrorBox, Loading } from "../../components/ui";
import { useLoad, useTaxonomy } from "../../hooks";
import { fmtWhite } from "../../verdict";

const PAGE = 10;

/**
 * The student's mistakes, game by game (newest first). The student acknowledges each one
 * ("I've seen this"); a later mistake of a kind they already acknowledged is flagged again.
 * The coach sees the same list read-only, including what the student acknowledged.
 */
export function MistakesTab({ studentId, viewer }: { studentId: string; viewer: "student" | "coach" }) {
  const [offset, setOffset] = useState(0);
  const { data, error, loading, refresh } = useLoad<MistakesPage>(
    `/students/${studentId}/mistakes?limit=${PAGE}&offset=${offset}`,
  );
  const tax = useTaxonomy();
  const isStudent = viewer === "student";
  const sets = useLoad<PuzzleSetList>(`/students/${studentId}/puzzle-sets`);
  // The latest puzzle set for each mistake (game, ply).
  const puzzles = new Map<string, PuzzleSet>();
  for (const s of [...(sets.data?.sets ?? [])].reverse()) {
    if (s.source) puzzles.set(`${s.source.game_id}/${s.source.ply}`, s);
  }

  return (
    <section>
      <p className="muted small">
        {isStudent
          ? "Every analyzed game, with the mistakes Stockfish found in your moves. Open a mistake on the board to see why, then acknowledge it. If you make the same kind of mistake again later, it is flagged."
          : "Your student's analyzed games and the mistakes found in them. The student acknowledges each mistake; you can follow along here."}
      </p>
      {loading && !data && <Loading />}
      <ErrorBox error={error} />
      {data && data.total_games === 0 && (
        <Empty>
          {isStudent ? (
            <>
              No analyzed games yet. <Link to="/?tab=games">Add and analyze your games</Link> first.
            </>
          ) : (
            "No analyzed games yet."
          )}
        </Empty>
      )}
      {data?.games.map((g) => (
        <GameCard key={g.game_id} g={g} tax={tax} canAcknowledge={isStudent} onChange={refresh} puzzles={puzzles} />
      ))}
      {data && data.total_games > PAGE && (
        <div className="row">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            Newer games
          </button>
          <span className="muted small">
            Games {offset + 1}–{Math.min(offset + PAGE, data.total_games)} of {data.total_games}
          </span>
          <button disabled={offset + PAGE >= data.total_games} onClick={() => setOffset(offset + PAGE)}>
            Older games
          </button>
        </div>
      )}
    </section>
  );
}

function GameCard({
  g,
  tax,
  canAcknowledge,
  onChange,
  puzzles,
}: {
  g: GameMistakes;
  tax: ReturnType<typeof useTaxonomy>;
  canAcknowledge: boolean;
  onChange: () => Promise<void>;
  puzzles: Map<string, PuzzleSet>;
}) {
  const n = g.mistakes.length;
  return (
    <article className="card game-mistakes" data-testid="game-mistakes">
      <header className="game-mistakes-head">
        <h3>
          <Link to={`/games/${g.game_id}`}>
            {g.white_name} – {g.black_name}
          </Link>
        </h3>
        <span className="muted small">
          {g.played_at ?? "no date"} · {g.result} · you played {g.student_color}
        </span>
        <span className="spacer" />
        {n === 0 ? (
          <Badge kind="ok">no mistakes</Badge>
        ) : (
          <Badge kind={g.acknowledged === n ? "ok" : "warn"}>
            {n} mistake{n > 1 ? "s" : ""} · {g.acknowledged} acknowledged
          </Badge>
        )}
      </header>
      {n > 0 && (
        <ol className="mistake-list">
          {g.mistakes.map((m) => (
            <MistakeRow
              key={m.ply}
              gameId={g.game_id}
              m={m}
              tax={tax}
              canAcknowledge={canAcknowledge}
              onChange={onChange}
              puzzleSet={puzzles.get(`${g.game_id}/${m.ply}`)}
            />
          ))}
        </ol>
      )}
    </article>
  );
}

function MistakeRow({
  gameId,
  m,
  tax,
  canAcknowledge,
  onChange,
  puzzleSet,
}: {
  gameId: string;
  m: Mistake;
  tax: ReturnType<typeof useTaxonomy>;
  canAcknowledge: boolean;
  onChange: () => Promise<void>;
  puzzleSet?: PuzzleSet;
}) {
  const url = `/games/${gameId}/mistakes/${m.ply}/acknowledgement`;
  const kinds = m.types.filter((t) => t.skill_code !== "unclassified");
  return (
    <li className={`mistake ${m.verdict ?? ""} ${m.acknowledged_at ? "seen" : ""}`} data-testid="mistake">
      <div className="mistake-move">
        <Link to={`/games/${gameId}?ply=${m.ply}`} className="mistake-san">
          {m.move_number}
          {m.ply % 2 ? "." : "…"} {m.san}
          {m.symbol && <span className="move-symbol">{m.symbol}</span>}
        </Link>
        <span className={`verdict-label ${m.verdict ?? ""}`}>{m.label}</span>
        {m.eval_before && m.eval_after && (
          <span className="muted small evalnum">
            {fmtWhite(m.eval_before.cp, m.eval_before.mate)} → {fmtWhite(m.eval_after.cp, m.eval_after.mate)}
          </span>
        )}
      </div>
      <div className="mistake-body">
        {m.best_move_san && m.best_move_san !== m.san && (
          <p className="small">
            Better was <b>{m.best_move_san}</b>
            {m.best_line_san.length > 1 && <span className="muted">: {m.best_line_san.slice(0, 5).join(" ")}</span>}
          </p>
        )}
        {m.reasons.length > 0 && (
          <ul className="small reasons">
            {m.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
        <p className="small kinds">
          {kinds.length > 0 ? (
            kinds.map((t) => (
              <Badge key={`${t.skill_code}/${t.subskill_code}/${t.motif_kind}`}>
                {skillLabel(tax, t.skill_code, t.subskill_code)}
                {t.motif_kind ? ` (${t.motif_kind})` : ""}
              </Badge>
            ))
          ) : (
            <span className="muted">Engine-confirmed error; no specific pattern verified.</span>
          )}
        </p>
        {m.flagged_again && (
          <p className="small again" data-testid="flagged-again">
            <Badge kind="warn">again</Badge> You already acknowledged this kind of mistake in the game vs{" "}
            <Link to={`/games/${m.flagged_again.game_id}?ply=${m.flagged_again.ply}`}>
              {m.flagged_again.opponent}
              {m.flagged_again.played_at && `, ${m.flagged_again.played_at}`}, move {m.flagged_again.move_number}
            </Link>
            .
          </p>
        )}
        {!m.flagged_again && kinds.some((t) => t.earlier.length > 0) && (
          <p className="small muted">
            Also in earlier games:{" "}
            {kinds
              .flatMap((t) => t.earlier)
              .slice(0, 3)
              .map((e, i) => (
                <span key={`${e.game_id}/${e.ply}`}>
                  {i > 0 && ", "}
                  <Link to={`/games/${e.game_id}?ply=${e.ply}`}>vs {e.opponent}</Link>
                </span>
              ))}
          </p>
        )}
      </div>
      <div className="mistake-ack">
        <PuzzleControl gameId={gameId} ply={m.ply} set={puzzleSet} canCreate={canAcknowledge} />
        {m.acknowledged_at ? (
          <>
            <Badge kind="ok">acknowledged {m.acknowledged_at.slice(0, 10)}</Badge>
            {canAcknowledge && (
              <ActionButton className="linklike small" onClick={async () => { await del(url); await onChange(); }}>
                undo
              </ActionButton>
            )}
          </>
        ) : canAcknowledge ? (
          <ActionButton onClick={async () => { await put(url); await onChange(); }}>Acknowledge</ActionButton>
        ) : (
          <span className="muted small">not acknowledged yet</span>
        )}
      </div>
    </li>
  );
}

/** "Puzzles like this" for one mistake: four Lichess puzzles of its kind, getting harder. */
function PuzzleControl({
  gameId,
  ply,
  set,
  canCreate,
}: {
  gameId: string;
  ply: number;
  set?: PuzzleSet;
  canCreate: boolean;
}) {
  const navigate = useNavigate();
  if (set) {
    return (
      <Link to={`/puzzles/${set.set_id}`} className="small" data-testid="puzzle-progress">
        Puzzles {set.solved}/{set.puzzles.length} solved
      </Link>
    );
  }
  if (!canCreate) return null;
  return (
    <ActionButton
      className="primary"
      onClick={async () => {
        const created = await post<PuzzleSet>(`/games/${gameId}/mistakes/${ply}/puzzles`);
        navigate(`/puzzles/${created.set_id}`);
      }}
    >
      Puzzles like this
    </ActionButton>
  );
}
