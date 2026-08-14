import { useState, type FormEvent } from "react";
import { api } from "../api";
import PreferencesForm from "./PreferencesForm";

export default function Onboarding({ onDone }: { onDone: (id: string) => void }) {
  const [email, setEmail] = useState("");
  const [userId, setUserId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submitEmail(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await api.createUser(email.trim());
      setUserId(user.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (userId) {
    return (
      <div className="card">
        <h1>Tell us what you're after</h1>
        <p className="muted">
          We'll alert you the day a matching role is posted at the companies you
          pick.
        </p>
        <PreferencesForm
          userId={userId}
          initialProfile=""
          initialWatchlist={[]}
          submitLabel="Start watching"
          onSaved={() => onDone(userId)}
        />
      </div>
    );
  }

  return (
    <div className="card narrow">
      <h1>Be first in the pile</h1>
      <p className="muted">
        Day-one alerts for new roles at your target companies, filtered to your
        resume.
      </p>
      <form onSubmit={submitEmail} className="stack">
        <label>
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
        </label>
        {error && <div className="error">{error}</div>}
        <button className="primary" disabled={busy}>
          {busy ? "…" : "Continue"}
        </button>
      </form>
    </div>
  );
}
