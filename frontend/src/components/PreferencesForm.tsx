import { useState, type FormEvent } from "react";
import {
  api,
  LEVELS,
  PLACES,
  ARRANGEMENTS,
  placeFor,
  arrangementFor,
  type Level,
  type PlaceId,
  type ArrangementId,
  type Preferences,
} from "../api";

// The whole of onboarding: three questions, all optional, all defaulted to
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
  const [place, setPlace] = useState<PlaceId>(placeFor(initial));
  const [arrangement, setArrangement] = useState<ArrangementId>(
    arrangementFor(initial),
  );
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
      await api.setPreferences({
        levels: [...levels],
        us_only: PLACES.find((p) => p.id === place)!.us,
        remote_only: ARRANGEMENTS.find((a) => a.id === arrangement)!.remote,
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
        <legend>Where</legend>
        <div className="choices">
          {PLACES.map((p) => (
            <label key={p.id} className="choice">
              <input
                type="radio"
                name="place"
                value={p.id}
                checked={place === p.id}
                onChange={() => setPlace(p.id)}
              />
              <span>
                {p.label}
                {"hint" in p && <span className="hint inline">{p.hint}</span>}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className="field">
        <legend>Work arrangement</legend>
        <div className="choices">
          {ARRANGEMENTS.map((a) => (
            <label key={a.id} className="choice">
              <input
                type="radio"
                name="arrangement"
                value={a.id}
                checked={arrangement === a.id}
                onChange={() => setArrangement(a.id)}
              />
              <span>
                {a.label}
                <span className="hint inline">{a.hint}</span>
              </span>
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
