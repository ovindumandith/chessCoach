import { useSearchParams } from "react-router-dom";

import { useAuth } from "../auth";
import { Empty } from "../components/ui";
import { CoachingTab } from "./student/CoachingTab";
import { ExercisesTab } from "./student/ExercisesTab";
import { GamesTab } from "./student/GamesTab";
import { ProfileTab } from "./student/ProfileTab";
import { ProgressTab } from "./student/ProgressTab";

const TABS = [
  ["exercises", "Exercises"],
  ["coaching", "Lessons"],
  ["profile", "My profile"],
  ["progress", "Progress"],
  ["games", "My games"],
] as const;

/** A student's own dashboard. */
export function StudentHome() {
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "exercises";
  const own = me?.students.find((s) => s.access_level === "self");
  if (!own) return <Empty>Your account is not linked to a student record yet. Ask your coach.</Empty>;
  const id = own.student_id;

  return (
    <main>
      <h1>Your training</h1>
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
      {tab === "exercises" && <ExercisesTab studentId={id} isStudent />}
      {tab === "coaching" && <CoachingTab studentId={id} />}
      {tab === "profile" && <ProfileTab studentId={id} canRebuild={false} />}
      {tab === "progress" && <ProgressTab studentId={id} />}
      {tab === "games" && <GamesTab studentId={id} canEdit={false} />}
    </main>
  );
}
