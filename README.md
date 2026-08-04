# Job Posting Watcher

Checks a set of company career pages for jobs that appeared since the last
run. The intended workflow is daily: run it once, read the report, and apply
to anything new on day one before the listing gets buried.

Each company keeps a persistent snapshot of every job ID ever seen. A run
fetches the current listings, diffs them against that snapshot, reports what
is new, and merges the results back into the snapshot. Reported jobs carry the
site's own job-detail URL, so a listing can be opened and applied to directly.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/pip install -e .
```

`playwright install chromium` is required for Meta, the only company not on a
JSON board API. Runs that skip it (`--company` on any platform company) need
no browser.

The editable install (`pip install -e .`) makes the `jobwatch` package
importable from `run.py` and the test suite.

Role-fit filtering calls the Claude API, so a key is required unless every run
passes `--all-roles`:

```bash
export ANTHROPIC_API_KEY=...
```

## Usage

```bash
.venv/bin/python run.py                         # all registered companies
.venv/bin/python run.py --company Stripe        # one company (repeatable)
.venv/bin/python run.py --dry-run               # scrape and report, no state write
.venv/bin/python run.py --verbose               # progress + filtered-out jobs on stderr
.venv/bin/python run.py --all-roles             # skip the role-fit filter
```

Combine flags as needed, e.g. `--company Meta --dry-run --verbose`.

`--verbose` prints every job the role filter dropped, with the reason. Worth
using for the first few runs to check the filter against your own judgement.

A non-zero exit code means at least one company returned `FAILED` or
`BLOCKED`. Check the report for details.

On a normal (non-dry-run) run, a dated JSON report is written under
`output/YYYY-MM-DD.json`.

### First run vs. daily runs (seeding)

The first run for any company is a **seed run**. It fetches every current
listing, saves them all to `state/<company>.json`, and reports
`seeded N jobs, no alerts` — nothing is flagged as new. Board sizes vary
widely: SpaceX seeds ~2,100 jobs, OpenAI ~740, Databricks ~800, Stripe ~540,
Linear ~24. Seeding all 25 companies stores roughly 8,100 listings.

This is deliberate. Without seeding, day one would dump hundreds of "new"
jobs that have been open for weeks. Real alerting starts on the second run:
only jobs whose IDs were not in the snapshot are reported. Two consecutive
runs against unchanged live sites should report zero new jobs on the second
pass — that is the property that makes daily use trustworthy.

Run it daily after the initial seed. Greenhouse and Ashby answer a whole board
in one request, so those 24 companies finish in about 35 seconds. Workday caps
a page at 20 results, so seeding its three companies costs ~196 requests and
several minutes — but results come newest-first, and the engine stops
paginating at the first page with no unseen ids, so a routine run reads one or
two pages per company.

Netflix costs a further ~23 seconds because its board must be read in full
(see above). OpenAI's board is the largest single download at ~11 MB, since
Ashby inlines full job descriptions.

Run it in the **early evening**. Postings appear through the business day, so
an end-of-day run catches everything posted that day while it is still hours
old; a morning run would miss the whole preceding day.

## Report statuses

| Status | Meaning |
|--------|---------|
| `seeded N jobs, no alerts` | First run for this company; snapshot created, nothing flagged. |
| `no new jobs` | Snapshot existed; nothing new since last run. |
| `N new` | New jobs found; titles, locations, and apply URLs are listed. |
| `FAILED` | Fetch or parse error (timeout, HTTP error, zero jobs when snapshot is non-empty, etc.). Most often the site's HTML changed and the scraper's selectors need updating. |
| `BLOCKED` | Site returned 403 or 429 — rate-limited or bot-detected. |
| `SUSPICIOUS` | More than 80% of current jobs look "new" against an existing snapshot, suggesting the site changed its job ID or URL scheme. New jobs are listed but the snapshot is **not** updated until the scraper is fixed. |

`FAILED` and `BLOCKED` are deliberately loud: a company cannot silently go
dark. Fix the scraper or retry later rather than ignoring a failed section.

## Currently tracked companies

29 companies are watched: 28 through four shared platform scrapers, plus
Meta's custom portal. The remaining names in `companies.txt` (44 total) are a target
list — see "Scaling to the rest" below.

| Source | Companies | Fetch mode |
|--------|-----------|------------|
| Greenhouse board API | Airbnb, Anthropic, Block, Cloudflare, Coinbase, Databricks, Dropbox, Figma, Jane Street, Lyft, MongoDB, Pinterest, Reddit, SpaceX, Stripe, Twitch, Vercel, Waymo | static HTTP |
| Ashby posting API | Linear, Notion, OpenAI, Plaid, Ramp, Snowflake | static HTTP |
| Workday CXS API | CrowdStrike, NVIDIA, Salesforce | JSON POST |
| Eightfold | Netflix | static HTTP |
| Custom portal | Meta | headless browser |

**Both platforms are the upstream source, not a mirror.** Recruiters post into
Greenhouse or Ashby and the company's careers page renders from it — Anthropic's
page links out to `job-boards.greenhouse.io`, Cloudflare's to
`boards.greenhouse.io`, Stripe embeds a `greenhouseId`. Reading the board API
is therefore at least as fresh as the careers page, and measurably so: on
2026-08-03 Anthropic's page and its board API returned an identical 399 jobs
with zero divergence in either direction, while the API was serving postings
3.8 hours old.

Two consequences worth knowing:

- **Greenhouse, Ashby, and Eightfold give an exact `posted_date`**
  (`first_published` / `publishedAt` / `t_create`). **Workday only gives
  prose** — "Posted 5 Days Ago" — so its dates are approximate, and "Posted
  30+ Days Ago" is left unset rather than invented as exactly 30. Meta gives
  nothing, so its recency comes purely from snapshot diffing.
- **Netflix is read in full on every run.** Its Eightfold board is not ordered
  by recency despite accepting `sort_by=timestamp`: of its 481 postings, the 15
  newest were spread across pages 1 to 22 of 49. The engine's usual early stop
  assumes newest-first ordering, so that company sets `paginate_fully` and
  costs ~49 requests (about 23 seconds) every run rather than one or two
  pages.
- **Stripe's careers page is a filtered view** of its board — 544 jobs on the
  API against 513 on the page. Migrating it surfaced 34 listings the page never
  showed.

Meta is the only company still needing a headless browser, so a run that skips
it needs no Playwright at all.

## Adding a company

**If the company is on Greenhouse or Ashby**, add one line to `BOARDS` in
`jobwatch/scrapers/greenhouse.py` or `jobwatch/scrapers/ashby.py`, mapping its
name to its board slug. Nothing else — no new module, no new test. Confirm the
slug first with `python tools/probe_ats.py <name>`.

**Otherwise** it needs its own module, following `jobwatch/scrapers/meta.py`:

1. Create `jobwatch/scrapers/<company>.py` with a `CompanyConfig` and a
   `Scraper` subclass implementing `parse()` (and `next_page_url()` if the
   site paginates).
2. Register the scraper instance in `jobwatch/registry.py`.
3. Save a real page (or API response) into `tests/fixtures/` and add a parser
   test under `tests/test_scraper_<company>.py`.

## Scaling to the rest

`tools/probe_ats.py` identifies which platform each company in `companies.txt`
uses. As of 2026-08-03, 28 of 44 sit on a usable platform and are all built:

| Platform | Companies | Status |
|----------|-----------|--------|
| Greenhouse | 18 | done — shared scraper |
| Workday | CrowdStrike, NVIDIA, Salesforce | done — shared scraper |
| Eightfold | Netflix | done — shared scraper |
| Ashby | OpenAI (736 jobs), Snowflake, Ramp, Plaid, Notion, Linear | done — shared scraper |
| SmartRecruiters | Canva | not built (single company) |
| iCIMS | GitHub | not built; fingerprinted |
| Eightfold, blocked | Microsoft | tenant answers 403 `Not authorized for PCSX` to the public jobs API |
| Custom portals | Google, Amazon, Apple, Uber, Tesla, Snap, DoorDash, Rippling, ByteDance, Two Sigma, Hudson River Trading | one scraper each, no leverage |

LinkedIn is excluded deliberately: it matches three different boards
(Greenhouse 53 jobs, Lever 23), none of them plausibly its real volume, so it
needs individual recon rather than an assumed slug.

## Project layout

```
run.py                  CLI entry point
jobwatch/
  engine.py             fetch, diff, snapshot merge for one company
  fetch.py              static HTTP and Playwright rendering
  diff.py               find jobs not in the snapshot
  state.py              load/save/merge per-company JSON snapshots
  report.py             format stdout report and write dated JSON
  registry.py           maps company name → scraper instance
  models.py             Job, CompanyConfig, FetchMode
  filters.py            report-time role-fit filtering via the Claude API
  scrapers/             base.py, greenhouse.py (18), ashby.py (6),
                        workday.py (3), eightfold.py (1), meta.py
state/                  per-company snapshots + filter cache (gitignored)
output/                 dated JSON reports (gitignored)
tests/                  181 tests, fixture-backed parser and unit tests
tests/fixtures/         saved HTML/JSON for offline parser tests
companies.txt           full target company list (most not yet scraped)
```

## Known limitations

- **Role-fit filtering judges the title and location only.** `jobwatch/filters.py`
  sends each new job's title, company, and location to Claude, which decides
  against the candidate profile in that module whether the role is a general
  backend or full-stack IC job at the target level **and workable from the US**.
  It never reads the job description, so a role whose title hides its real
  content can be misjudged. There is no
  "uncertain" bucket — a job marked irrelevant is not reported at all, which is
  why the prompt is told to keep genuinely borderline listings. Run `--verbose`
  to see what was dropped, or `--all-roles` to see everything.
- **Verdicts are cached** in `state/filter_cache.json`, keyed by company,
  title, and location, so a repeated listing is judged once. Location is part
  of the key because it is part of the verdict: the same title is a keep in
  Seattle and a drop in Bengaluru. Editing `CANDIDATE_PROFILE` or the
  instructions in `filters.py` invalidates the whole cache automatically.
- **A failed classification is loud, not silent.** Snapshots are written before
  filtering, so a job dropped by an API failure would never be reported again.
  When classification fails the run prints every new job unfiltered and exits
  non-zero.
- **No scheduling** — run `run.py` manually (e.g. via cron) when you want a
  check.
- **Meta scope** — only software engineering roles, because that is what the
  configured career URL returns. Expanding to other teams means a different
  entry URL or an additional scraper.
- **Site fragility** — career pages change markup without notice. A scraper
  that worked yesterday may `FAILED` tomorrow until its selectors are updated.

## Tests

```bash
.venv/bin/pytest          # full suite (181 tests)
.venv/bin/pytest -v       # verbose
```

Parser tests use fixtures under `tests/fixtures/` and do not hit the network.
Integration-style tests for fetch and the CLI use mocks. The role filter is
tested with an injected stub classifier, so no test calls the Claude API.
