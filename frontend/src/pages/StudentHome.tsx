import { useRef } from "react";
import { useSearchParams } from "react-router-dom";

import type { Game, Page } from "../api";
import { useAuth } from "../auth";
import { Empty } from "../components/ui";
import { useLoad } from "../hooks";
import { ChessLlmTab } from "./student/ChessLlmTab";
import { ExercisesTab } from "./student/ExercisesTab";
import { GamesTab } from "./student/GamesTab";
import { ProfileTab } from "./student/ProfileTab";
import { ProgressTab } from "./student/ProgressTab";
import { MistakesTab } from "./student/MistakesTab";

// The flow: add games -> see the mistakes -> train on them.
const TABS = [
  ["games", "My games"],
  ["mistakes", "My mistakes"],
  ["exercises", "Exercises"],
  ["llm", "Chess LLM"],
  ["profile", "My profile"],
  ["progress", "Progress"],
] as const;

const READY = new Set(["analyzed", "deepening"]);

/** A student's own dashboard. */
export function StudentHome() {
  const { me } = useAuth();
  const own = me?.students.find((s) => s.access_level === "self");
  if (!own) return <Empty>Your account is not linked to a student record yet. Ask your coach.</Empty>;
  return <Training studentId={own.student_id} />;
}

function Training({ studentId: id }: { studentId: string }) {
  const [params, setParams] = useSearchParams();
  const setTab = (key: string) => setParams({ tab: key });
  const { data, refresh } = useLoad<Page<Game>>(`/students/${id}/games?limit=200`);
  const games = data?.items ?? [];
  const added = games.length;
  const analyzed = games.filter((g) => g.analysis_status && READY.has(g.analysis_status)).length;

  // A new student starts where there is something to do: adding games. Decided once, so the
  // page does not jump to another tab when their first upload lands.
  const initial = useRef<string | null>(null);
  if (initial.current === null && data) initial.current = added === 0 ? "games" : "mistakes";
  const tab = params.get("tab") ?? initial.current;

  return (
    <main>
      <h1>Your training</h1>
      {data && analyzed === 0 && (
        <ol className="card getting-started" aria-label="Getting started">
          <li className={added ? "done" : ""}>
            <b>Add your games</b> in{" "}
            <button type="button" className="linklike" onClick={() => setTab("games")}>
              My games
            </button>{" "}
            (a .pgn export from Lichess, Chess.com or a tournament).
            {added > 0 && <span className="muted small"> {added} added.</span>}
          </li>
          <li>
            <b>See your mistakes.</b> Stockfish checks every move; <i>My mistakes</i> lists what it found, game by game.
          </li>
          <li>
            <b>Train.</b> In <i>Exercises</i>, your AI coach recommends what to practise and builds exercises from your own mistakes.
          </li>
        </ol>
      )}
      <nav className="tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "active" : ""}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </nav>
      {tab === "exercises" && <ExercisesTab studentId={id} />}
      {tab === "llm" && <ChessLlmTab studentId={id} />}
      {tab === "mistakes" && <MistakesTab studentId={id} viewer="student" />}
      {tab === "profile" && <ProfileTab studentId={id} />}
      {tab === "progress" && <ProgressTab studentId={id} />}
      {tab === "games" && <GamesTab studentId={id} viewer="student" onChange={refresh} />}
    </main>
  );
}
