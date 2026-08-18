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

-- Whether this row came from a company's initial seed — the run that records a
-- whole pre-existing board at once. The public feed wants genuinely-new
-- postings, so it excludes these.
--
-- Recorded at write time rather than derived at read time. The feed used to ask
-- "is first_seen_at later than this company's earliest?", which meant a
-- min()-per-company aggregate over the entire table on every request, on top of
-- a sequential scan the indexes above could not serve. Both are gone now.
--
-- Like first_seen_at, it is set once on insert and never updated: a routine
-- run's upsert leaves an existing row's flag alone (see _UPSERT_SQL in
-- jobwatch/store.py).
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS is_seed boolean NOT NULL DEFAULT false;

-- One-time backfill for rows written before the column existed, applying
-- exactly the rule the old query derived: a company's seed is everything at its
-- earliest first_seen_at (a seed writes the whole board at one timestamp). The
-- `NOT is_seed` guard makes re-applying this file a no-op rather than redundant
-- work, and leaves rows the ingester has already flagged untouched.
UPDATE jobs j SET is_seed = true
FROM (SELECT company, min(first_seen_at) AS seeded_at FROM jobs GROUP BY company) s
WHERE j.company = s.company
  AND j.first_seen_at = s.seeded_at
  AND NOT j.is_seed;

-- Serves the feed's query outright: the partial predicate keeps the seeded
-- back-catalogue (the bulk of the table) out of the index, and the column order
-- matches RecentPostings' ORDER BY exactly, so the top N rows are read straight
-- off the index with no sort.
CREATE INDEX IF NOT EXISTS jobs_recent_idx
    ON jobs (first_seen_at DESC, job_id) WHERE NOT is_seed;

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

-- When a user was last run through matching. NULL means never; the matcher uses
-- it as the lower bound (with each company's added_at) on which jobs to consider,
-- so a routine run only looks at jobs first seen since the last one.
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_matched_at timestamptz;

-- When a user was last emailed a digest. The digest run emails matches staged
-- since this moment, then advances it, so a match is emailed exactly once.
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_digest_at timestamptz;

-- Cache of role-fit verdicts, keyed by a hash of the prompt+profile so two users
-- with identical profiles share judgments and a profile edit invalidates cleanly.
-- Location is part of the key because it is part of the verdict (a title is a keep
-- in Seattle and a drop in Bengaluru); a null location is normalised to ''.
CREATE TABLE IF NOT EXISTS fit_verdicts (
    profile_hash text        NOT NULL,
    company      text        NOT NULL,
    title        text        NOT NULL,
    location     text        NOT NULL DEFAULT '',
    keep         boolean     NOT NULL,
    reason       text        NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (profile_hash, company, title, location)
);

-- Per-user staged keepers: jobs that passed the fit filter for this user, ready
-- to be shown or delivered. One row per (user, job); re-running matching never
-- duplicates a row.
CREATE TABLE IF NOT EXISTS matches (
    user_id    uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company    text        NOT NULL,
    job_id     text        NOT NULL,
    reason     text        NOT NULL DEFAULT '',
    matched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, company, job_id)
);

CREATE INDEX IF NOT EXISTS matches_user_matched_at_idx
    ON matches (user_id, matched_at DESC);

-- Magic-link login tokens. Only the SHA-256 of the emailed token is stored, so a
-- database leak yields nothing usable. Single-use (used_at) and short-lived
-- (expires_at); the raw token lives only in the email.
CREATE TABLE IF NOT EXISTS login_tokens (
    token_hash text        PRIMARY KEY,
    user_id    uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    used_at    timestamptz
);

-- Session tokens issued after a login link is verified. Same hash-only storage;
-- a row is a bearer credential, revocable by deletion (logout).
CREATE TABLE IF NOT EXISTS sessions (
    token_hash text        PRIMARY KEY,
    user_id    uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);

-- ---------------------------------------------------------------------------
-- Enrichment: the structured facts a subscriber filters on.
--
-- Kept in its own table rather than as columns on `jobs` to preserve the
-- ingestion contract: Python owns every column of `jobs`, Go owns this. It also
-- means a routine re-scrape can never clobber a verdict as a side effect of the
-- upsert.
--
-- Only title-and-location-derived facts live here. We deliberately do not open
-- the posting to enrich it — a filter is only offered when the listing itself
-- carries the signal (see `level`'s 'unknown').
CREATE TABLE IF NOT EXISTS job_enrichment (
    company    text        NOT NULL,
    job_id     text        NOT NULL,
    -- The title this verdict was judged from. A board that re-titles a req in
    -- place keeps its job_id, and the old verdict would then describe a title
    -- that no longer exists — so the enricher re-judges when this stops
    -- matching, rather than serving a stale level.
    title_hash text        NOT NULL,
    is_swe     boolean     NOT NULL,
    -- intern | new_grad | junior | mid | senior | staff | unknown
    --
    -- 'unknown' is a first-class value, not a failure: roughly a third of real
    -- software titles carry no level at all ("Software Engineer, Ads"). Those
    -- rows are always delivered regardless of a subscriber's level filter,
    -- because hiding a role on absent evidence is a worse error than showing
    -- one extra.
    level      text        NOT NULL,
    is_us      boolean     NOT NULL,
    is_remote  boolean     NOT NULL,
    reason     text        NOT NULL DEFAULT '',
    judged_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company, job_id)
);

-- Serves the digest and the feed: both ask for recent, non-seed, US software
-- roles and then narrow by level.
CREATE INDEX IF NOT EXISTS job_enrichment_keep_idx
    ON job_enrichment (company, job_id) WHERE is_swe;

-- ---------------------------------------------------------------------------
-- Subscriber preferences.
--
-- A subscriber is just a `users` row that has confirmed. The profile/watchlist
-- tables stay for the personal-fit matcher, but nothing in the digest path
-- requires them any more: the MVP sends every confirmed subscriber the same
-- query, narrowed only by these columns.

-- Double opt-in. NULL means the address was entered but the link was never
-- clicked; those accounts are never emailed a digest.
ALTER TABLE users ADD COLUMN IF NOT EXISTS confirmed_at    timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS unsubscribed_at timestamptz;

-- Empty array means "every level", which is the default and the recommended
-- setting. A non-empty array is an opt-in narrowing; 'unknown' rows bypass it.
ALTER TABLE users ADD COLUMN IF NOT EXISTS levels      text[]  NOT NULL DEFAULT '{}';
ALTER TABLE users ADD COLUMN IF NOT EXISTS us_only     boolean NOT NULL DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS remote_only boolean NOT NULL DEFAULT false;

-- Accounts created before double opt-in existed had no way to confirm, and they
-- did opt in — they clicked a magic link to create the account. Treat them as
-- confirmed rather than silently dropping them from every future digest.
UPDATE users SET confirmed_at = created_at WHERE confirmed_at IS NULL;

-- ---------------------------------------------------------------------------
-- Product analytics.
--
-- One append-only row per tracked action. `props` is jsonb so a new event can
-- carry new fields without a migration — this table exists to answer the launch
-- gates (reach, activation, click-through, retention), and those questions will
-- change shape faster than a schema should.
--
-- user_id is nullable and ON DELETE SET NULL: deleting an account must not
-- delete the history that a signup and a click happened, but must stop the row
-- pointing at a person.
CREATE TABLE IF NOT EXISTS events (
    id         bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text        NOT NULL,
    user_id    uuid        REFERENCES users(id) ON DELETE SET NULL,
    props      jsonb       NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS events_name_created_idx ON events (name, created_at DESC);
CREATE INDEX IF NOT EXISTS events_user_idx ON events (user_id, created_at DESC);
