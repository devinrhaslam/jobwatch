// Typed client for the Go backend. All calls go to same-origin /api, which Vite
// proxies to the backend in dev (see vite.config.ts). Authenticated calls carry
// the session token as a bearer header.

// In dev this is unset and calls go to same-origin /api, which Vite proxies to
// the backend. In production it's the backend's absolute URL (set at build time),
// and the backend's CORS allows this origin.
const BASE = import.meta.env.VITE_API_BASE || "/api";
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

// The levels a subscriber can filter on. `unknown` is deliberately absent: it
// is not something you opt into, it is what always comes through — about a third
// of real software titles name no level, and those reach everyone.
export const LEVELS = [
  { id: "intern", label: "Internship" },
  { id: "new_grad", label: "New grad" },
  { id: "junior", label: "Junior" },
  { id: "mid", label: "Mid-level" },
  { id: "senior", label: "Senior" },
  { id: "staff", label: "Staff+" },
] as const;

export type Level = (typeof LEVELS)[number]["id"];

export interface Preferences {
  levels: Level[];
  us_only: boolean;
  remote_only: boolean;
}

export interface UserView extends Preferences {
  id: string;
  email: string;
  created_at: string;
  confirmed: boolean;
  subscribed: boolean;
  // Unused by the MVP; see the note at the bottom of this file.
  profile: string | null;
  watchlist: string[];
}

export interface Stats {
  companies: number;
  jobs: number;
  new_today: number;
}

export interface Job {
  company: string;
  job_id: string;
  title: string;
  url: string;
  location: string | null;
  posted_date: string | null;
  first_seen_at: string;
  last_seen_at: string;
  // Resolved server-side so the web app and the digest email show the same icon.
  logo_url: string;
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
  stats: () => req<Stats>("/stats"),
  // The public home-page feed: recent software-engineering roles across all
  // companies in the last `sinceHours`, newest first. No auth. The /feed endpoint
  // classifies "is this software engineering" and returns only the keepers.
  recentJobs: (sinceHours = 24, limit = 200) => {
    const since = new Date(Date.now() - sinceHours * 3600_000).toISOString();
    return req<Job[]>(
      `/feed?since=${encodeURIComponent(since)}&limit=${limit}`,
    );
  },
  // Recent roles, widening the window if it comes back empty.
  //
  // A quiet night — or a cron that missed — must never render an empty list to
  // someone who just arrived from a launch post, so this falls back to the most
  // recent 30 days and reports that it did, letting the caller relabel.
  recentJobsOrLatest: async (
    hours: number,
  ): Promise<{ jobs: Job[]; stale: boolean }> => {
    const fresh = await api.recentJobs(hours, 200);
    if (fresh.length > 0) return { jobs: fresh, stale: false };
    return { jobs: await api.recentJobs(24 * 30, 200), stale: true };
  },
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
  setPreferences: (prefs: Preferences) =>
    req<void>("/me/preferences", { method: "PUT", body: prefs }),
};

// Not bound here: /companies, /me/profile, /me/watchlist, /me/match and
// /me/matches. Those back the resume-based personal-fit matcher, which is built
// and tested server-side but is not part of the MVP — the free product filters
// on level and location, which are answerable from a job title. Re-add the
// client methods when there is a paid tier to put behind them.
