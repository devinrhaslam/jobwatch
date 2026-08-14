import { useState, type FormEvent } from "react";
import { api } from "../api";

export default function Login() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [devLink, setDevLink] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.authRequest(email.trim());
      setSent(true);
      setDevLink(res.dev_link ?? null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div className="card narrow">
        <h1>Check your email</h1>
        <p className="muted">
          We sent a sign-in link to <strong>{email}</strong>. Click it to
          continue — no password needed.
        </p>
        {devLink && (
          <p className="muted small">
            Dev shortcut (email isn't wired up yet):{" "}
            <a href={devLink}>open your sign-in link</a>
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="card narrow">
      <h1>Be first in the pile</h1>
      <p className="muted">
        Day-one alerts for new roles at your target companies, filtered to your
        resume. Enter your email and we'll send a sign-in link.
      </p>
      <form onSubmit={submit} className="stack">
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
          {busy ? "…" : "Send me a link"}
        </button>
      </form>
    </div>
  );
}
