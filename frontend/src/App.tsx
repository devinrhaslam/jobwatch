import { useState } from "react";
import Onboarding from "./components/Onboarding";
import Dashboard from "./components/Dashboard";

// No auth yet: the signed-in user is just an id held in localStorage, a dev
// stand-in until magic-link auth lands. Signing out forgets it.
const USER_KEY = "jobwatch.userId";

export default function App() {
  const [userId, setUserId] = useState<string | null>(() =>
    localStorage.getItem(USER_KEY),
  );

  function signIn(id: string) {
    localStorage.setItem(USER_KEY, id);
    setUserId(id);
  }
  function signOut() {
    localStorage.removeItem(USER_KEY);
    setUserId(null);
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          job<span>watch</span>
        </div>
        {userId && (
          <button className="link" onClick={signOut}>
            sign out
          </button>
        )}
      </header>
      <main className="container">
        {userId ? (
          <Dashboard userId={userId} />
        ) : (
          <Onboarding onDone={signIn} />
        )}
      </main>
      <footer className="foot">
        Dev preview · accounts are unauthenticated until magic-link auth lands
      </footer>
    </div>
  );
}
