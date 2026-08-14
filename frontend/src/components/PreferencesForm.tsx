import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";

// The profile textarea plus a searchable company multi-select, saving both the
// profile and watchlist for the signed-in user. Used by first-time Setup and the
// dashboard's edit view.
export default function PreferencesForm({
  initialProfile,
  initialWatchlist,
  submitLabel,
  onSaved,
}: {
  initialProfile: string;
  initialWatchlist: string[];
  submitLabel: string;
  onSaved: () => void;
}) {
  const [profile, setProfile] = useState(initialProfile);
  const [companies, setCompanies] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(initialWatchlist),
  );
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .companies()
      .then(setCompanies)
      .catch((e) => setError((e as Error).message));
  }, []);

  function toggle(company: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(company)) next.delete(company);
      else next.add(company);
      return next;
    });
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.setProfile(profile.trim());
      await api.setWatchlist([...selected]);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const shown = companies.filter((c) =>
    c.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <form onSubmit={save} className="stack">
      <label>
        Your target role
        <textarea
          rows={5}
          required
          value={profile}
          onChange={(e) => setProfile(e.target.value)}
          placeholder="e.g. Senior backend engineer, ~8 years, Go / TypeScript / Python. US-remote. Not interested in data, ML, mobile, frontend-only, security, infra/SRE, or management roles."
        />
      </label>

      <div>
        <div className="row between center">
          <label className="tight">
            Companies to watch{" "}
            <span className="muted">({selected.size} selected)</span>
          </label>
          <input
            className="search"
            placeholder="filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        <div className="picker">
          {companies.length === 0 && (
            <span className="muted">loading companies…</span>
          )}
          {shown.map((company) => (
            <label
              key={company}
              className={"chip" + (selected.has(company) ? " on" : "")}
            >
              <input
                type="checkbox"
                checked={selected.has(company)}
                onChange={() => toggle(company)}
              />
              {company}
            </label>
          ))}
        </div>
      </div>

      {error && <div className="error">{error}</div>}
      <button className="primary" disabled={busy || selected.size === 0}>
        {busy ? "saving…" : submitLabel}
      </button>
    </form>
  );
}
