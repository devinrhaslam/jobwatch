# Job Posting Watcher

Checks a set of company career pages for jobs that appeared since the last
run. The intended workflow is daily: run it once, read the report, and apply
to anything new on day one before the listing gets buried.

Each company keeps a persistent snapshot of every job ID ever seen. A run
fetches the current listings, diffs them against that snapshot, reports what
is new, and merges the results back into the snapshot. Job URLs in the report
resolve to live application pages.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/pip install -e .
```

`playwright install chromium` is required — Cloudflare and Meta cannot be
scraped without a headless browser. The editable install (`pip install -e .`)
makes the `jobwatch` package importable from `run.py` and the test suite.

## Usage

```bash
.venv/bin/python run.py                         # all registered companies
.venv/bin/python run.py --company Stripe        # one company (repeatable)
.venv/bin/python run.py --dry-run               # scrape and report, no state write
.venv/bin/python run.py --verbose               # per-company progress on stderr
```

Combine flags as needed, e.g. `--company Meta --dry-run --verbose`.

A non-zero exit code means at least one company returned `FAILED` or
`BLOCKED`. Check the report for details.

On a normal (non-dry-run) run, a dated JSON report is written under
`output/YYYY-MM-DD.json`.

### First run vs. daily runs (seeding)

The first run for any company is a **seed run**. It fetches every current
listing, saves them all to `state/<company>.json`, and reports
`seeded N jobs, no alerts` — nothing is flagged as new. On a typical first
seed that is roughly 400 jobs at Anthropic, 513 at Stripe, 284 at Cloudflare,
and 65 at Meta.

This is deliberate. Without seeding, day one would dump hundreds of "new"
jobs that have been open for weeks. Real alerting starts on the second run:
only jobs whose IDs were not in the snapshot are reported. Two consecutive
runs against unchanged live sites should report zero new jobs on the second
pass — that is the property that makes daily use trustworthy.

Run it daily after the initial seed. Each run takes roughly 40 seconds for all
four companies; most of that time is headless-browser rendering for Cloudflare
and Meta.

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

Four companies have working scrapers. The remaining names in `companies.txt`
(~44 total) are a target list, not yet implemented.

| Company | Fetch mode | Notes |
|---------|------------|-------|
| Anthropic | static HTTP | ~400 jobs on first seed |
| Stripe | static HTTP | ~513 jobs on first seed |
| Cloudflare | headless browser | ~284 jobs; only company that exposes a real posted date |
| Meta | headless browser | ~65 jobs; entry URL is pre-filtered to software engineering roles, newest-first, 10 per page |

Anthropic, Stripe, and Meta do not expose posted dates on their listing pages.
Recency comes entirely from snapshot diffing — a job is "new" when its ID first
appears, not when the page says it was posted.

## Adding a company

1. Create `jobwatch/scrapers/<company>.py` with a `CompanyConfig` and a
   `Scraper` subclass implementing `parse()` (and `next_page_url()` if the
   site paginates).
2. Register the scraper instance in `jobwatch/registry.py`.
3. Save a real page (or API response) into `tests/fixtures/` and add a parser
   test under `tests/test_scraper_<company>.py`.

Follow the existing scrapers for patterns: Anthropic and Stripe use static
HTTP; Cloudflare and Meta use Playwright rendering with a `wait_for_selector`.

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
  filters.py            pass-through stub for future role-fit filtering
  scrapers/             one module per company (base.py + four scrapers)
state/                  per-company snapshots (gitignored)
output/                 dated JSON reports (gitignored)
tests/                  76 tests, fixture-backed parser and unit tests
tests/fixtures/         saved HTML/JSON for offline parser tests
companies.txt           full target company list (most not yet scraped)
```

## Known limitations

- **Role-fit filtering** is not implemented. `jobwatch/filters.py` is a
  deliberate pass-through seam; snapshots always store every job regardless
  of seniority or title match, so widening filters later requires no
  re-seeding.
- **No scheduling** — run `run.py` manually (e.g. via cron) when you want a
  check.
- **Meta scope** — only software engineering roles, because that is what the
  configured career URL returns. Expanding to other teams means a different
  entry URL or an additional scraper.
- **Site fragility** — career pages change markup without notice. A scraper
  that worked yesterday may `FAILED` tomorrow until its selectors are updated.

## Tests

```bash
.venv/bin/pytest          # full suite (76 tests)
.venv/bin/pytest -v       # verbose
```

Parser tests use fixtures under `tests/fixtures/` and do not hit the network.
Integration-style tests for fetch and the CLI use mocks.
