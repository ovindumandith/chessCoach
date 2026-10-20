import { useParams, useSearchParams } from "react-router-dom";

import type { Student } from "../api";
import { ErrorBox, Loading } from "../components/ui";
import { useLoad } from "../hooks";
import { AccountTab } from "./student/AccountTab";
import { CoachingTab } from "./student/CoachingTab";
import { ExercisesTab } from "./student/ExercisesTab";
import { GamesTab } from "./student/GamesTab";
import { ProfileTab } from "./student/ProfileTab";
import { ProgressTab } from "./student/ProgressTab";
import { ReviewTab } from "./student/ReviewTab";

const TABS = [
  ["games", "Games"],
  ["review", "Review findings"],
  ["profile", "Profile"],
  ["coaching", "Lessons"],
  ["exercises", "Exercises"],
  ["progress", "Progress"],
  ["account", "Account"],
] as const;

/** Coach view of one student. */
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
          {tab === "games" && <GamesTab studentId={id} canEdit />}
          {tab === "review" && <ReviewTab studentId={id} canReview />}
          {tab === "profile" && <ProfileTab studentId={id} canRebuild />}
          {tab === "coaching" && <CoachingTab studentId={id} />}
          {tab === "exercises" && <ExercisesTab studentId={id} isStudent={false} />}
          {tab === "progress" && <ProgressTab studentId={id} />}
          {tab === "account" && <AccountTab studentId={id} />}
        </>
      )}
    </main>
  );
}
