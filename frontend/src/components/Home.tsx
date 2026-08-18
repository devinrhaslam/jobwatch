import { useEffect, useState } from "react";
import { api, type Job, type Stats } from "../api";
import SignupForm from "./SignupForm";
import CompanyIcon from "./CompanyIcon";
import { relativeTime } from "../time";

// The public landing page. The feed is the centrepiece rather than a list below
// the fold, because it *is* the demo: the pitch is "we see these the day they
// appear", and the only convincing way to make that claim is to show the roles
// with their real ages next to them.
export default function Home() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    // Stats are decoration; a failure there must not blank the page.
    api.stats().then(setStats).catch(() => {});

    api
      .recentJobsOrLatest(24)
      .then(({ jobs, stale }) => {
        setJobs(jobs);
        setStale(stale);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="stack">
      <section className="hero">
        <h1>
          Every software engineering job,
          <br />
          <em>the day it's posted</em>
        </h1>
        <p className="lede">
          We read the career pages of {stats ? stats.companies : "hundreds of"}{" "}
          top companies every night and email you what's new. A role counts as
          new the first time we ever see it — not whenever a job board decides to
          bump its date.
        </p>

        <SignupForm />

        {stats && (
          <dl className="proof">
            <div>
              <dt>{stats.companies.toLocaleString()}</dt>
              <dd>companies tracked</dd>
            </div>
            <div>
              <dt>{stats.jobs.toLocaleString()}</dt>
              <dd>roles in the index</dd>
            </div>
            <div>
              <dt>{stats.new_today.toLocaleString()}</dt>
              <dd>posted in the last 24h</dd>
            </div>
          </dl>
        )}
      </section>

      <section className="card">
        <div className="row between center">
          <h2>{stale ? "Most recent roles" : "New in the last 24 hours"}</h2>
          {jobs.length > 0 && <span className="count">{jobs.length}</span>}
        </div>
        {loading ? (
          <p className="muted">Loading the latest roles…</p>
        ) : error ? (
          <div className="error">{error}</div>
        ) : jobs.length === 0 ? (
          <p className="muted">Nothing to show yet — check back soon.</p>
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
      </section>
    </div>
  );
}
