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
        ) : user.profile === null ? (
          <Setup onSaved={reload} />
        ) : (
          <Dashboard user={user} onReload={reload} />
        )}
      </main>
      <footer className="foot">
        Dev preview · passwordless sign-in by magic link
      </footer>
    </div>
  );
}
