import { BrowserRouter, Link, Navigate, NavLink, Route, Routes } from "react-router-dom";

import { useAuth } from "./auth";
import { Loading } from "./components/ui";
import { ExercisePlay } from "./pages/ExercisePlay";
import { GameViewer } from "./pages/GameViewer";
import { Login } from "./pages/Login";
import { Mistakes } from "./pages/Mistakes";
import { PuzzleSetPage } from "./pages/PuzzleSetPage";
import { StudentDetail } from "./pages/StudentDetail";
import { StudentHome } from "./pages/StudentHome";
import { Students } from "./pages/Students";

export function App() {
  const { me, loading, logout } = useAuth();
  if (loading) return <Loading />;
  if (!me) return <Login />;
  const isStudent = me.role === "student";

  return (
    <BrowserRouter>
      <header className="topbar">
        <Link to="/" className="brand">
          ChessMentor AI
        </Link>
        {!isStudent && (
          <nav className="topnav" aria-label="Coach">
            <NavLink to="/" end>
              Students
            </NavLink>
            <NavLink to="/mistakes">Mistakes across students</NavLink>
          </nav>
        )}
        <span className="muted small">
          {me.email} ({me.role})
        </span>
        <button onClick={logout}>Sign out</button>
      </header>
      <Routes>
        <Route path="/" element={isStudent ? <StudentHome /> : <Students />} />
        {!isStudent && <Route path="/students/:id" element={<StudentDetail />} />}
        {!isStudent && <Route path="/mistakes" element={<Mistakes />} />}
        <Route path="/games/:id" element={<GameViewer />} />
        <Route path="/exercises/:id" element={<ExercisePlay />} />
        <Route path="/puzzles/:setId" element={<PuzzleSetPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
