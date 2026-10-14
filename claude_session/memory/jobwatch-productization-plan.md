---
name: jobwatch-productization-plan
description: The plan to turn jobwatch from a personal CLI into a multi-tenant job-alerts SaaS
metadata: 
  node_type: memory
  type: project
  originSessionId: d44cbd7a-25fb-4516-9d5f-2d668beef03c
  modified: 2026-08-14T20:21:58.436Z
---

jobwatch (the `applications` repo) is being productized from a single-user CLI
into a multi-tenant service: **day-one job alerts for a curated set of target
companies, personalized to each user's resume**. Positioned as an *alerting*
product, not a search engine — deliberately not competing with Hiring Cafe on
index size. The two real advantages it leans on: honest freshness (a job is
"new" the first run its id is ever seen, immune to gamed posted_date fields) and
per-user LLM role-fit filtering.

**Stack (decided by the user):** Python scrapers → Postgres (the integration
contract; the two services never call each other) → Go backend (users, matching,
delivery, API) → React + TypeScript frontend. MVP surface = email digest + a
minimal web app.

**Phased plan (all work on branch `phase0-postgres-store`, unpushed):** Phase 0 =
Postgres cutover (DONE: `SnapshotStore` boundary, `PostgresSnapshotStore` with
first_seen-preserving upsert, `schema.sql`, `docker-compose.yml`,
`tools/migrate_json_to_postgres.py`, Postgres opt-in via `JOBWATCH_DATABASE_URL`).
Phase 1 = Go read API over `jobs` (DONE: `backend/` module, `/companies`,
`/jobs`, `/health`; pgx + stdlib routing). Phase 2 = users/watchlists/profiles
(DONE) + matching engine (DONE: `fit_verdicts` cache, `matches`, seeding-boundary
candidate selection) + real Claude fit classifier (DONE: `backend/internal/server/claude.go`,
ports `filters.py` via `anthropic-sdk-go`, model `claude-opus-5`, gated live test).
Magic-link auth = DONE: login_tokens + sessions (hash-only storage, single-use
login tokens, 30-day sessions), /auth/request + /auth/verify, bearer middleware,
endpoints moved from /users/{id} to auth-scoped /me; React uses a real session
via a /verify landing. Phase 3 onboarding + matches UI = DONE (`frontend/`, Vite
+ React + TS, verified live in browser). Phase 4 email digest = DONE:
`RunDigests` + `cmd/digest` (a scheduler one-shot) match every eligible user and
email new matches once via a per-user last_digest_at cursor; `Mailer` interface
with a dev logMailer (real SMTP/Resend is a config swap). **Remaining to ship:**
a real email provider, a scheduled worker (Fargate scheduled task) to run
cmd/digest + ingestion, CORS on the backend for a separate frontend origin,
session hardening (httpOnly cookies), CAN-SPAM footer on real sends, and AWS
provisioning. Branch has ~13 commits, still unpushed. Phase 5 = ops
(scraper-health from `company_runs`), privacy policy, request-a-company.

Backend runs against local Docker Postgres; Go/Python integration tests gate on
`JOBWATCH_TEST_DATABASE_URL` and skip without it. The dev machine's Docker
Desktop daemon has dropped repeatedly mid-session — relaunch with `open -a Docker`.

**Decisions to hold:** develop against local Docker Postgres, defer AWS/RDS to
Phase 4/5 (code is DSN-portable, so no rework). No paid ads for MVP — job seekers
are low-LTV/churny; lead with a public "new roles today" feed as top-of-funnel +
communities (r/csMajors, Blind, Show HN). **MVP launches free** (decided
2026-08-13) — no billing model in Phase 2. Relates to [[job-search-targeting-criteria]] (the same
curated-target-companies instinct) and [[jobwatch-dead-links-are-the-recurring-bug]]
(don't market before links are reliable).
