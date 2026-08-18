import { useCallback, useEffect, useState } from "react";
import {
  api,
  clearSession,
  locationLabel,
  LEVELS,
  type Job,
  type UserView,
} from "../api";
import PreferencesForm from "./PreferencesForm";
import CompanyIcon from "./CompanyIcon";
import { relativeTime } from "../time";

export default function Dashboard({
  user,
  onReload,
}: {
  user: UserView;
  onReload: () => Promise<void>;
}) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stale, setStale] = useState(false);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");

  // The signed-in view shows the same feed a digest would carry, so someone can
  // see what they're subscribed to without waiting for tomorrow's email.
  const load = useCallback(async () => {
    try {
      const { jobs, stale } = await api.recentJobsOrLatest(48);
      setJobs(jobs);
      setStale(stale);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function deleteAccount() {
    if (
      !window.confirm(
        "Delete your account and all your data? This can't be undone.",
      )
    )
      return;
    try {
      await api.deleteAccount();
    } catch {
      // even if the call fails, forget the session locally
    }
    clearSession();
    window.location.assign("/");
  }

  if (editing) {
    return (
      <div className="card">
        <h1>What you get</h1>
        <PreferencesForm
          initial={{
            levels: user.levels,
            us_only: user.us_only,
            remote_only: user.remote_only,
          }}
          submitLabel="Save"
          onSaved={async () => {
            setEditing(false);
            await onReload();
          }}
        />
      </div>
    );
  }

  const levelLabels = user.levels.length
    ? LEVELS.filter((l) => user.levels.includes(l.id)).map((l) => l.label)
    : ["Every level"];

  return (
    <div className="stack">
      <div className="card">
        <div className="row between center">
          <div>
            <div className="muted small">signed in as</div>
            <div className="email">{user.email}</div>
          </div>
          <button className="ghost" onClick={() => setEditing(true)}>
            Edit what you get
          </button>
        </div>
        {!user.subscribed && (
          <div className="note warn">
            You're unsubscribed — no digests are being sent. Save your
            preferences to start them again.
          </div>
        )}
        <dl className="summary">
          <div>
            <dt>Levels</dt>
            <dd>
              {levelLabels.map((l) => (
                <span key={l} className="chip on static">
                  {l}
                </span>
              ))}
            </dd>
          </div>
          <div>
            <dt>Location</dt>
            <dd className="plain">{locationLabel(user)}</dd>
          </div>
        </dl>
      </div>

      <div className="card">
        <h2>{stale ? "Most recent roles" : "New in the last 48 hours"}</h2>
        {error && <div className="error">{error}</div>}
        {jobs.length === 0 ? (
          <p className="muted">Nothing to show yet — check back tomorrow.</p>
        ) : (
          <ul className="matches">
            {jobs.map((j) => (
              <li key={j.company + j.job_id} className="match">
                <CompanyIcon company={j.company} src={j.logo_url} />
                <div className="match-main">
                  <a
                    href={j.url}
                    target="_blank"
                    rel="noreferrer"
                    className="match-title"
                  >
                    {j.title}
                  </a>
                  <div className="match-meta">
                    {j.company}
                    {j.location ? ` · ${j.location}` : ""}
                  </div>
                </div>
                <div className="match-when">{relativeTime(j.first_seen_at)}</div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="dangerzone">
        <button className="danger-link" onClick={deleteAccount}>
          Delete account and data
        </button>
      </div>
    </div>
  );
}
