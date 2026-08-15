import { useEffect, useState } from "react";
import { api, type Job } from "../api";
import SignupForm from "./SignupForm";
import CompanyIcon from "./CompanyIcon";

// The public landing page: a signup call-to-action over the firehose of every
// new posting in the last day. No login required.
export default function Home() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .recentJobs(24, 200)
      .then(setJobs)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="stack">
      <div className="hero card">
        <h1>Every software engineering job, the day it's posted</h1>
        <p className="muted">
          The latest engineering openings across the world's top companies,
          straight from their career pages. Make an account and we'll email you
          just the ones that fit your resume.
        </p>
        <SignupForm />
      </div>

      <div className="card">
        <h2>
          New engineering roles in the last 24 hours
          {jobs.length ? ` (${jobs.length})` : ""}
        </h2>
        {loading ? (
          <p className="muted">Loading the latest roles…</p>
        ) : error ? (
          <div className="error">{error}</div>
        ) : jobs.length === 0 ? (
          <p className="muted">
            No new roles in the last day — check back soon.
          </p>
        ) : (
          <ul className="matches">
            {jobs.map((j) => (
              <li key={j.company + j.job_id} className="match">
                <CompanyIcon company={j.company} />
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
                <div className="match-when">
                  {new Date(j.first_seen_at).toLocaleDateString()}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
