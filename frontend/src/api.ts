// Typed client for the Go backend. All calls go to same-origin /api, which Vite
// proxies to the backend in dev (see vite.config.ts).

const BASE = "/api";

export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface UserView extends User {
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
  const res = await fetch(BASE + path, {
    method: opts.method ?? "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
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
  createUser: (email: string) =>
    req<User>("/users", { method: "POST", body: { email } }),
  getUser: (id: string) => req<UserView>(`/users/${id}`),
  setProfile: (id: string, profile: string) =>
    req<void>(`/users/${id}/profile`, { method: "PUT", body: { profile } }),
  setWatchlist: (id: string, companies: string[]) =>
    req<void>(`/users/${id}/watchlist`, { method: "PUT", body: { companies } }),
  runMatch: (id: string) =>
    req<MatchResult>(`/users/${id}/match`, { method: "POST" }),
  matches: (id: string) => req<Match[]>(`/users/${id}/matches?limit=200`),
};
