import { useState, type FormEvent } from "react";

import { errorText, post } from "../../api";
import { ErrorBox } from "../../components/ui";

export function AccountTab({ studentId }: { studentId: string }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await post(`/students/${studentId}/account`, { email, password });
      setDone(email);
      setPassword("");
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <section>
      <form onSubmit={submit} className="card inline-form">
        <h2>Student login</h2>
        <p className="muted small">
          Gives this student their own account. They can see only their own games, profile, lessons and exercises.
        </p>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Initial password (10+ characters)
          <input type="password" minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <ErrorBox error={error} />
        {done && <p className="ok">Account created for {done}.</p>}
        <button type="submit" className="primary">
          Create account
        </button>
      </form>
    </section>
  );
}
