import { Chess } from "chess.js";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { errorText, post, skillLabel, type PuzzleSet, type PuzzleView } from "../api";
import { useAuth } from "../auth";
import { Board } from "../components/Board";
import { ActionButton, Badge, ErrorBox, Loading } from "../components/ui";
import { useLoad, useTaxonomy } from "../hooks";

const SIDE = { white: "White", black: "Black" } as const;

/** Four Lichess puzzles of one mistake's kind, easiest first. */
export function PuzzleSetPage() {
  const { setId = "" } = useParams();
  const { me } = useAuth();
  const { data, error, loading, setData, refresh } = useLoad<PuzzleSet>(`/puzzle-sets/${setId}`);
  const tax = useTaxonomy();
  const [index, setIndex] = useState<number | null>(null);
  const isStudent = me?.role === "student";

  if (loading && !data) return <Loading />;
  if (!data) return <ErrorBox error={error} />;
  const firstOpen = data.puzzles.findIndex((p) => p.status === "open");
  const shown = index ?? (firstOpen === -1 ? 0 : firstOpen);
  const current = data.puzzles[shown];

  const replace = (p: PuzzleView) => {
    // Stay on this puzzle (to show its solution) until the student asks for the next one.
    if (index === null) setIndex(shown);
    setData({
      ...data,
      puzzles: data.puzzles.map((q) => (q.id === p.id ? p : q)),
      solved: data.puzzles.filter((q) => (q.id === p.id ? p : q).result === "solved").length,
    });
    void refresh(); // the puzzle rating changes after each decided puzzle
  };

  return (
    <main className="puzzle-page">
      <p className="small">
        <Link to={isStudent ? "/?tab=mistakes" : `/students/${data.student_id}?tab=mistakes`}>← Mistakes</Link>
      </p>
      <h1>Puzzles: {skillLabel(tax, data.skill_code, data.subskill_code)}</h1>
      <p className="muted">
        {data.source ? (
          <>
            For your mistake{" "}
            <Link to={`/games/${data.source.game_id}?ply=${data.source.ply}`}>
              {data.source.move_number}
              {data.source.ply % 2 ? "." : "…"} {data.source.san} vs {data.source.opponent}
            </Link>
            .{" "}
          </>
        ) : (
          "From your training recommendation. "
        )}
        Each puzzle is harder than the one before. Puzzles from the{" "}
        <a href="https://database.lichess.org/#puzzles" target="_blank" rel="noreferrer">
          Lichess puzzle database
        </a>{" "}
        (CC0).
      </p>
      <nav className="puzzle-steps" aria-label="Puzzles in this set">
        {data.puzzles.map((p, i) => (
          <button
            key={p.id}
            className={`puzzle-step ${p.result ?? ""} ${p === current ? "current" : ""}`}
            aria-current={p === current}
            onClick={() => setIndex(i)}
          >
            <span className="step-n">{i + 1}</span>
            <span className="step-rating">{p.rating}</span>
            <span className="step-state">{p.result === "solved" ? "✓" : p.result === "failed" ? "✗" : ""}</span>
          </button>
        ))}
        <span className="muted small puzzle-rating" data-testid="puzzle-rating">
          Your puzzle rating for this: {data.rating_now ?? data.rating_before}
          {data.rating_now !== null && data.rating_now !== data.rating_before && (
            <> (was {data.rating_before})</>
          )}
        </span>
      </nav>
      {current && (
        <PuzzlePlayer
          key={current.id}
          p={current}
          canPlay={isStudent}
          onChange={replace}
          onNext={
            data.puzzles.indexOf(current) < data.puzzles.length - 1
              ? () => setIndex(data.puzzles.indexOf(current) + 1)
              : undefined
          }
        />
      )}
    </main>
  );
}

function after(fen: string, uci: string): string {
  const chess = new Chess(fen);
  chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
  return chess.fen();
}

function PuzzlePlayer({
  p,
  canPlay,
  onChange,
  onNext,
}: {
  p: PuzzleView;
  canPlay: boolean;
  onChange: (p: PuzzleView) => void;
  onNext?: () => void;
}) {
  const [fen, setFen] = useState(p.fen);
  const [lastMove, setLastMove] = useState(p.last_move);
  const [feedback, setFeedback] = useState<"right" | "wrong" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [remount, setRemount] = useState(0);
  const [review, setReview] = useState(0); // step through the solution once finished
  useEffect(() => {
    setFen(p.fen);
    setLastMove(p.last_move);
  }, [p.fen, p.last_move]);

  const open = p.status === "open";
  const done = !open && p.solution && p.start_fen;

  async function play(uci: string) {
    setError(null);
    try {
      const res = await post<{ correct: boolean; reply: string | null; puzzle: PuzzleView }>(
        `/puzzles/${p.id}/moves`,
        { move: uci },
      );
      if (!res.correct) {
        setFeedback("wrong");
        setRemount((n) => n + 1); // the piece goes back
        onChange(res.puzzle);
        return;
      }
      setFeedback("right");
      setFen(after(fen, uci));
      setLastMove(uci);
      // Show the opponent's answer a moment later, like on Lichess.
      window.setTimeout(() => onChange(res.puzzle), res.reply ? 450 : 0);
    } catch (e) {
      setError(errorText(e));
      setRemount((n) => n + 1);
    }
  }

  // Solution review: the position after `review` solution moves.
  let reviewFen = p.start_fen ?? p.fen;
  let reviewLast = p.last_move;
  if (done) {
    for (const uci of p.solution!.slice(0, review)) {
      reviewFen = after(reviewFen, uci);
      reviewLast = uci;
    }
  }

  return (
    <div className="puzzle-workspace">
      <div key={remount}>
        <Board
          fen={done ? reviewFen : fen}
          orientation={p.student_side}
          onMove={open && canPlay ? (uci) => void play(uci) : undefined}
          lastMove={done ? reviewLast : lastMove}
          size="min(560px, calc(100vh - 250px), calc(100vw - 32px))"
        />
      </div>
      <section className="card puzzle-panel" data-testid="puzzle-panel">
        <h2>
          {open ? `${SIDE[p.student_side]} to move` : p.result === "solved" ? "Solved" : "Not solved this time"}
        </h2>
        <p className="muted small">
          Puzzle rating {p.rating} (±{p.rating_deviation}) · theme {p.theme}
        </p>
        {open && (
          <>
            <p>
              Find the best move{p.moves_left > 1 ? `; ${p.moves_left} of your moves to go` : ""}.
            </p>
            {feedback === "wrong" && (
              <p className="feedback wrong" role="status">
                That's not it. This puzzle now counts as missed, but keep trying to find the solution.
              </p>
            )}
            {feedback === "right" && (
              <p className="feedback right" role="status">
                Correct, keep going.
              </p>
            )}
            {canPlay && (
              <ActionButton onClick={async () => onChange(await post<PuzzleView>(`/puzzles/${p.id}/reveal`))}>
                Show the solution
              </ActionButton>
            )}
          </>
        )}
        {done && (
          <>
            <p>
              Solution: <b className="evalnum">{p.solution!.join(" ")}</b>
            </p>
            <div className="row">
              <button onClick={() => setReview(Math.max(0, review - 1))} disabled={review === 0}>
                ◀
              </button>
              <span className="small">
                {review} / {p.solution!.length}
              </span>
              <button onClick={() => setReview(Math.min(p.solution!.length, review + 1))} disabled={review === p.solution!.length}>
                ▶
              </button>
            </div>
            <p className="small">
              <a href={p.lichess_url!} target="_blank" rel="noreferrer">
                This puzzle on Lichess
              </a>
            </p>
            {onNext && (
              <button className="primary" onClick={onNext}>
                Next puzzle (harder)
              </button>
            )}
            {!onNext && <Badge kind="ok">Set finished</Badge>}
          </>
        )}
        <ErrorBox error={error} />
      </section>
    </div>
  );
}
