import PreferencesForm from "./PreferencesForm";

// Shown once, right after a new account's first sign-in (no profile yet).
export default function Setup({ onSaved }: { onSaved: () => void }) {
  return (
    <div className="card">
      <h1>Tell us what you're after</h1>
      <p className="muted">
        We'll alert you the day a matching role is posted at the companies you
        pick.
      </p>
      <PreferencesForm
        initialProfile=""
        initialWatchlist={[]}
        submitLabel="Start watching"
        onSaved={onSaved}
      />
    </div>
  );
}
