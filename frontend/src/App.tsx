import { useCallback, useEffect, useState } from "react";
import {
  api,
  clearSession,
  getSession,
  setSession,
  type UserView,
} from "./api";
import Home from "./components/Home";
import Setup from "./components/Setup";
import Dashboard from "./components/Dashboard";

export default function App() {
  const [user, setUser] = useState<UserView | null>(null);
  const [ready, setReady] = useState(false);
  // Setup is shown once, immediately after following a confirmation link — not
  // gated on an empty profile, since the MVP never asks for one.
  const [justConfirmed, setJustConfirmed] = useState(false);

  const reload = useCallback(async () => {
    setUser(await api.me());
  }, []);

  useEffect(() => {
    (async () => {
      // Magic-link landing: /verify?token=… exchanges the login token for a
      // session, then cleans the URL.
      const params = new URLSearchParams(window.location.search);
      const linkToken = params.get("token");
      if (linkToken && window.location.pathname === "/verify") {
        try {
          const { token, user } = await api.authVerify(linkToken);
          setSession(token);
          setUser(user);
          setJustConfirmed(true);
        } catch {
          clearSession();
        }
        window.history.replaceState({}, "", "/");
        setReady(true);
        return;
      }
      if (getSession()) {
        try {
          setUser(await api.me());
        } catch {
          clearSession();
        }
      }
      setReady(true);
    })();
  }, []);

  function signOut() {
    api.logout().catch(() => {});
    clearSession();
    setUser(null);
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          job<span>watch</span>
        </div>
        {user && (
          <button className="link" onClick={signOut}>
            sign out
          </button>
        )}
      </header>
      <main className="container">
        {!ready ? (
          <div className="card">Signing you in…</div>
        ) : !user ? (
          <Home />
        ) : justConfirmed ? (
          <Setup
            initial={{
              levels: user.levels,
              us_only: user.us_only,
              remote_only: user.remote_only,
            }}
            onSaved={async () => {
              // Reload before leaving Setup: the account in state predates the
              // save, so the dashboard would otherwise show the old filters.
              await reload();
              setJustConfirmed(false);
            }}
          />
        ) : (
          <Dashboard user={user} onReload={reload} />
        )}
      </main>
      <footer className="foot">
        Job listings are read from each company's own careers page. Links go
        straight to the employer.
      </footer>
    </div>
  );
}
