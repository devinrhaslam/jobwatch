import { type Match } from "../api";

export default function MatchList({ matches }: { matches: Match[] }) {
  if (matches.length === 0) {
    return (
      <p className="muted">
        No matches yet. Hit “Find matches now” to check for new postings at your
        companies.
      </p>
    );
  }
  return (
    <ul className="matches">
      {matches.map((m) => (
        <li key={m.company + m.job_id} className="match">
          <div className="match-main">
            <a
              href={m.url}
              target="_blank"
              rel="noreferrer"
              className="match-title"
            >
              {m.title}
            </a>
            <div className="match-meta">
              {m.company}
              {m.location ? ` · ${m.location}` : ""}
            </div>
            {m.reason && <div className="match-reason">{m.reason}</div>}
          </div>
          <div className="match-when">
            {new Date(m.first_seen_at).toLocaleDateString()}
          </div>
        </li>
      ))}
    </ul>
  );
}
