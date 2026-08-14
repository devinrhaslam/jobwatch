// Typed client for the Go backend. All calls go to same-origin /api, which Vite
// proxies to the backend in dev (see vite.config.ts). Authenticated calls carry
// the session token as a bearer header.

const BASE = "/api";
const SESSION_KEY = "jobwatch.session";

export function getSession(): string | null {
  return localStorage.getItem(SESSION_KEY);
}
export function setSession(token: string) {
  localStorage.setItem(SESSION_KEY, token);
}
export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}

export interface UserView {
  id: string;
  email: string;
  created_at: string;
  profile: string | null;
  watchlist: string[];
}

export interface MatchResult {
  evaluated: number;
  kept: number;
}

export interface Match {
  company: string;
  job_id: string;
  title: string;
  url: string;
  location: string | null;
  reason: string;
  matched_at: string;
  first_seen_at: string;
}

async function req<T>(
  path: string,
  opts: { method?: string; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body) headers["Content-Type"] = "application/json";
  const token = getSession();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(BASE + path, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let message = `request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.error) message = body.error;
    } catch {
      // non-JSON error body; keep the status message
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  companies: () => req<string[]>("/companies"),
  authRequest: (email: string) =>
    req<{ ok: boolean; dev_link?: string }>("/auth/request", {
      method: "POST",
      body: { email },
    }),
  authVerify: (token: string) =>
    req<{ token: string; user: UserView }>("/auth/verify", {
      method: "POST",
      body: { token },
    }),
  logout: () => req<void>("/auth/logout", { method: "POST" }),
  me: () => req<UserView>("/me"),
  deleteAccount: () => req<void>("/me", { method: "DELETE" }),
  setProfile: (profile: string) =>
    req<void>("/me/profile", { method: "PUT", body: { profile } }),
  setWatchlist: (companies: string[]) =>
    req<void>("/me/watchlist", { method: "PUT", body: { companies } }),
  runMatch: () => req<MatchResult>("/me/match", { method: "POST" }),
  matches: () => req<Match[]>("/me/matches?limit=200"),
};
