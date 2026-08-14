-- jobwatch storage schema.
--
-- This is the multi-tenant contract between the Python ingestion worker (which
-- writes `jobs` and `company_runs`) and the future Go backend (which reads
-- them). It is intentionally the whole Phase-0 data model, even though slice 2
-- only exercises `jobs`; keeping the schema in one reviewed place is cheaper
-- than growing it a table at a time.
--
-- Apply with:
--   psql "$JOBWATCH_DATABASE_URL" -f schema.sql
-- Every statement is idempotent, so re-applying it is safe.

-- Every job ever seen, one row per (company, job_id). `first_seen_at` is the
-- honest-freshness signal that replaces the old per-company JSON snapshot: it
-- is set once, on the first run that ever records an id, and never moved. A
-- routine run upserts the current board and only bumps `last_seen_at`.
CREATE TABLE IF NOT EXISTS jobs (
    company       text        NOT NULL,
    job_id        text        NOT NULL,
    title         text        NOT NULL,
    url           text        NOT NULL,
    location      text,
    -- Kept as the scraped ISO string rather than a date: some boards give an
    -- exact publish date, some give approximate prose, and some give nothing.
    -- Coercing to a date would invent precision the source did not provide.
    posted_date   text,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company, job_id)
);

-- Answers "what did this user get since their last digest" without a per-user
-- scan of the whole table.
CREATE INDEX IF NOT EXISTS jobs_company_first_seen_idx
    ON jobs (company, first_seen_at);

-- One row per company per run: the health signal that turns a FAILED/BLOCKED
-- scraper from a line skimmed in a terminal into something a dashboard can
-- surface, now that a broken scraper is customer-facing.
CREATE TABLE IF NOT EXISTS company_runs (
    id        bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company   text        NOT NULL,
    ran_at    timestamptz NOT NULL DEFAULT now(),
    status    text        NOT NULL,   -- seeded | ok | failed | blocked | suspicious
    jobs_read integer     NOT NULL DEFAULT 0,
    jobs_new  integer     NOT NULL DEFAULT 0,
    error     text
);

CREATE INDEX IF NOT EXISTS company_runs_company_ran_at_idx
    ON company_runs (company, ran_at DESC);

-- One account per email. gen_random_uuid() is built into Postgres 13+. Email is
-- normalised to lowercase by the application before it reaches here, so the
-- UNIQUE constraint is the real one-account-per-person rule.
CREATE TABLE IF NOT EXISTS users (
    id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    email      text        NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- The free-text description the fit filter judges against — this is the per-user
-- half of what filters.py currently holds as a single global CANDIDATE_PROFILE.
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id      uuid        PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    profile_text text        NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- A user's watchlist: which tracked companies they want alerts for. added_at is
-- the per-user seeding boundary — a company added today should only ever alert
-- on jobs first seen after this moment, never the back-catalogue.
CREATE TABLE IF NOT EXISTS user_companies (
    user_id  uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company  text        NOT NULL,
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, company)
);
