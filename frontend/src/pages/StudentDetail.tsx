import { useParams, useSearchParams } from "react-router-dom";

import type { Student } from "../api";
import { ErrorBox, Loading } from "../components/ui";
import { useLoad } from "../hooks";
import { AccountTab } from "./student/AccountTab";
import { CoachPlans } from "./student/ChessLlmTab";
import { CoachingTab } from "./student/CoachingTab";
import { GamesTab } from "./student/GamesTab";
import { MistakesTab } from "./student/MistakesTab";
import { ProfileTab } from "./student/ProfileTab";
import { ProgressTab } from "./student/ProgressTab";

const TABS = [
  ["games", "Games"],
  ["mistakes", "Mistakes"],
  ["profile", "Profile"],
  ["coaching", "Recommendations"],
  ["progress", "Progress"],
  ["account", "Account"],
] as const;

/** Coach view of one student: monitoring. The student adds games, gets lessons and trains. */
export function StudentDetail() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "games";
  const { data: student, error, loading } = useLoad<Student>(`/students/${id}`);

  return (
    <main>
      {loading && <Loading />}
      <ErrorBox error={error} />
      {student && (
        <>
          <h1>{student.display_name}</h1>
          <p className="muted small">PGN names: {student.aliases.join(", ") || "none"}</p>
          <nav className="tabs" role="tablist">
            {TABS.map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                className={tab === key ? "active" : ""}
                onClick={() => setParams({ tab: key })}
              >
                {label}
              </button>
            ))}
          </nav>
          {tab === "games" && <GamesTab studentId={id} viewer="coach" />}
          {tab === "mistakes" && <MistakesTab studentId={id} viewer="coach" />}
          {tab === "profile" && <ProfileTab studentId={id} />}
          {tab === "coaching" && (
            <>
              <CoachPlans studentId={id} />
              <CoachingTab studentId={id} canGenerate={false} />
            </>
          )}
          {tab === "progress" && <ProgressTab studentId={id} />}
          {tab === "account" && <AccountTab studentId={id} />}
        </>
      )}
    </main>
  );
}
