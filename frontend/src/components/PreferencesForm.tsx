import { useState, type FormEvent } from "react";
import {
  api,
  LEVELS,
  LOCATIONS,
  locationFor,
  type Level,
  type LocationId,
  type Preferences,
} from "../api";

// The whole of onboarding: two questions, both optional, both defaulted to
// "send me everything".
//
// This replaced a free-text profile plus a 267-item company multi-select. Two
// reasons. Filters here are answerable from the job title alone, which is all
// the pipeline reads — it never opens a posting, so it can only offer a filter
// the listing itself carries. And every question asked before the first email is
// a chance to lose someone who has not yet seen the product work.
export default function PreferencesForm({
  initial,
  submitLabel,
  onSaved,
}: {
  initial: Preferences;
  submitLabel: string;
  onSaved: () => void;
}) {
  const [levels, setLevels] = useState<Set<Level>>(new Set(initial.levels));
  const [location, setLocation] = useState<LocationId>(locationFor(initial));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function toggle(level: Level) {
    setLevels((prev) => {
      const next = new Set(prev);
      if (next.has(level)) next.delete(level);
      else next.add(level);
      return next;
    });
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const choice = LOCATIONS.find((l) => l.id === location)!;
      await api.setPreferences({
        levels: [...levels],
        us_only: choice.us,
        remote_only: choice.remote,
      });
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="stack">
      <fieldset className="field">
        <legend>Levels</legend>
        <p className="hint">
          Pick none to get every level — that's the recommended setting. Roles
          whose title doesn't state a level always come through either way.
        </p>
        <div className="picker">
          {LEVELS.map(({ id, label }) => (
            <label key={id} className={"chip" + (levels.has(id) ? " on" : "")}>
              <input
                type="checkbox"
                checked={levels.has(id)}
                onChange={() => toggle(id)}
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="field">
        <legend>Location</legend>
        <p className="hint">Anything outside this is left out of your email.</p>
        <div className="choices">
          {LOCATIONS.map(({ id, label }) => (
            <label key={id} className="choice">
              <input
                type="radio"
                name="location"
                value={id}
                checked={location === id}
                onChange={() => setLocation(id)}
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      {error && <div className="error">{error}</div>}
      <button className="primary" disabled={busy}>
        {busy ? "saving…" : submitLabel}
      </button>
    </form>
  );
}
