import PreferencesForm from "./PreferencesForm";
import { type Preferences } from "../api";

// Shown once, right after a new subscriber's first sign-in. Everything here is
// optional — they are already subscribed by this point, and the defaults send
// every US software role — so this is a chance to narrow, never a gate.
export default function Setup({
  initial,
  onSaved,
}: {
  initial: Preferences;
  onSaved: () => void;
}) {
  return (
    <div className="card">
      <h1>You're subscribed</h1>
      <p className="muted">
        Every new software engineering role at the companies we track, the day
        it's posted. Narrow it down if you like — or skip this and change your
        mind later from any email.
      </p>
      <PreferencesForm
        initial={initial}
        submitLabel="Save and finish"
        onSaved={onSaved}
      />
    </div>
  );
}
