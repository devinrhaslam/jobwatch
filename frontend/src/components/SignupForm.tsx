import { useState, type FormEvent } from "react";
import { api } from "../api";

// The email → magic-link call-to-action. Used as the signup prompt on the public
// home page. On success it shows the "check your email" state (and, in dev, the
// link itself, since real email isn't wired up yet).
export default function SignupForm() {
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
      <div className="signup-sent">
        <strong>Check your email</strong> — we sent a confirmation link to{" "}
        {email}. Click it and your first digest arrives tomorrow morning.
        {devLink && (
          <>
            {" "}
            <a href={devLink}>Open your sign-in link</a> (dev)
          </>
        )}
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="signup-row">
      <input
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@example.com"
        aria-label="Email"
      />
      <button className="primary" disabled={busy}>
        {busy ? "…" : "Get daily alerts"}
      </button>
      {error && <div className="error">{error}</div>}
    </form>
  );
}
