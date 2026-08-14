import { useCallback, useEffect, useState } from "react";
import { api, type Match, type UserView } from "../api";
import PreferencesForm from "./PreferencesForm";
import MatchList from "./MatchList";

export default function Dashboard({
  user,
  onReload,
}: {
  user: UserView;
  onReload: () => Promise<void>;
}) {
  const [matches, setMatches] = useState<Match[]>([]);
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadMatches = useCallback(async () => {
    try {
      setMatches(await api.matches());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    loadMatches();
  }, [loadMatches]);

  async function runMatch() {
    setBusy(true);
    setStatus("");
    setError("");
    try {
      const r = await api.runMatch();
      setStatus(
        `Checked ${r.evaluated} new posting${r.evaluated === 1 ? "" : "s"}, kept ${r.kept}.`,
      );
      await loadMatches();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <div className="card">
        <h1>Edit your preferences</h1>
        <PreferencesForm
          initialProfile={user.profile ?? ""}
          initialWatchlist={user.watchlist}
          submitLabel="Save"
          onSaved={async () => {
            setEditing(false);
            await onReload();
          }}
        />
      </div>
    );
  }

  return (
    <div className="stack">
      <div className="card">
        <div className="row between center">
          <div>
            <div className="muted small">signed in as</div>
            <div className="email">{user.email}</div>
          </div>
          <button className="ghost" onClick={() => setEditing(true)}>
            Edit preferences
          </button>
        </div>
        <div className="watchrow">
          {user.watchlist.map((c) => (
            <span key={c} className="chip on static">
              {c}
            </span>
          ))}
          {user.watchlist.length === 0 && (
            <span className="muted">No companies yet — add some.</span>
          )}
        </div>
      </div>

      <div className="card">
        <div className="row between center">
          <h2>Your matches</h2>
          <button className="primary" onClick={runMatch} disabled={busy}>
            {busy ? "checking…" : "Find matches now"}
          </button>
        </div>
        {status && <div className="note">{status}</div>}
        {error && <div className="error">{error}</div>}
        <MatchList matches={matches} />
      </div>
    </div>
  );
}
