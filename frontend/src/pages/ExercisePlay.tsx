import { useState } from "react";
import { useParams } from "react-router-dom";

import { errorText, post, type Exercise } from "../api";
import { useAuth } from "../auth";
import { Board } from "../components/Board";
import { ActionButton, Badge, ErrorBox, Loading } from "../components/ui";
import { useLoad } from "../hooks";

export function ExercisePlay() {
  const { id = "" } = useParams();
  const { me } = useAuth();
  const { data: ex, error, loading, setData } = useLoad<Exercise>(`/exercises/${id}`);
  const [hints, setHints] = useState<string[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [startedAt] = useState(() => Date.now());
  const isStudent = me?.role === "student";

  async function attempt(move: string) {
    if (!ex) return;
    setMoveError(null);
    try {
      const res = await post<{ correct: boolean; attempts_left: number; exercise: Exercise }>(
        `/exercises/${ex.id}/attempts`,
        { move, time_taken_ms: Date.now() - startedAt },
      );
      setData(res.exercise);
      setFeedback(
        res.correct
          ? "Correct!"
          : res.exercise.status === "failed"
            ? "Not this time. Here is the solution."
            : `Not quite. ${res.attempts_left} attempt(s) left.`,
      );
    } catch (e) {
      setMoveError(errorText(e)); // illegal moves are rejected and not recorded
    }
  }

  if (loading) return <Loading />;
  if (!ex) return <ErrorBox error={error} />;
  const open = ex.status === "open";
  const sol = ex.solution;

  return (
    <main className="exercise">
      <h1>{ex.prompt}</h1>
      <p className="muted small">
        {ex.purpose === "review" ? "From one of your games" : "Practice position"} · {ex.difficulty ?? "unrated"} ·{" "}
        <Badge kind={ex.status === "solved" ? "ok" : open ? "" : "warn"}>{ex.status}</Badge>
      </p>
      <div className="viewer">
        <Board
          fen={ex.start_fen}
          orientation={ex.side_to_move}
          onMove={open && isStudent ? (uci) => void attempt(uci) : undefined}
          bestMove={sol?.accepted_moves_uci[0]}
          size={420}
        />
        <div>
          {feedback && <p className={ex.status === "solved" ? "ok" : "warn"}>{feedback}</p>}
          <ErrorBox error={moveError} />
          {open && isStudent && (
            <>
              <p>Drag a piece to make your move. You have {ex.max_attempts - ex.attempts.length} attempt(s).</p>
              <TypedMove onSubmit={attempt} />
              <div className="row">
                <ActionButton
                  disabled={ex.hints_given >= ex.hints_available}
                  onClick={async () => {
                    const h = await post<{ hint: string }>(`/exercises/${ex.id}/hint`);
                    setHints([...hints, h.hint]);
                    setData({ ...ex, hints_given: ex.hints_given + 1 });
                  }}
                >
                  Hint ({ex.hints_available - ex.hints_given} left)
                </ActionButton>
                <ActionButton onClick={async () => setData(await post<Exercise>(`/exercises/${ex.id}/reveal`))}>
                  Show solution
                </ActionButton>
              </div>
            </>
          )}
          {open && !isStudent && <p className="muted">Only the student can answer this exercise.</p>}
          {hints.length > 0 && (
            <ol className="hints">
              {hints.map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ol>
          )}
          {ex.attempts.length > 0 && (
            <p className="small">
              Your moves:{" "}
              {ex.attempts.map((a) => (
                <Badge key={a.attempt_number} kind={a.is_correct ? "ok" : "warn"}>
                  {a.move_san}
                </Badge>
              ))}
            </p>
          )}
          {sol && (
            <div className="card">
              <p>
                Solution: <b>{sol.accepted_moves_san.join(" or ")}</b>
              </p>
              {sol.explanation && <p>{sol.explanation}</p>}
              {ex.purpose === "review" && sol.game_move && (
                <p className="muted">
                  In the game you played {sol.game_move.san} ({sol.game_move.eval_after} afterwards).
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

function TypedMove({ onSubmit }: { onSubmit: (move: string) => Promise<void> }) {
  const [text, setText] = useState("");
  return (
    <form
      className="row"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) void onSubmit(text.trim()).then(() => setText(""));
      }}
    >
      <input aria-label="Type a move" placeholder="or type it, e.g. Nf3" value={text} onChange={(e) => setText(e.target.value)} />
      <button type="submit">Submit</button>
    </form>
  );
}
