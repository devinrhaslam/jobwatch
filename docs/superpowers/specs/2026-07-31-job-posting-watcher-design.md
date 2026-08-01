# Job Posting Watcher — Design

**Date:** 2026-07-31
**Status:** Approved design, ready for implementation planning

## Problem

Applying to big tech roles on day one materially improves response odds. Checking ~59 companies' career pages by hand every day is not sustainable. We need a script that reports which jobs appeared at those companies since the last check, so the user can apply immediately.

A later phase filters results by role fit (e.g. Software Engineer vs. Senior vs. Staff), so the design must accommodate filtering without rework.

## Scope

**In scope (phase 1):**

- A framework for per-company career page scraping.
- Detection of newly posted jobs via snapshot diffing.
- Console output plus a per-run log file.
- Fully working scrapers for four pilot companies: Anthropic, Cloudflare, Stripe, Meta.
- Manual invocation from the command line.

**Out of scope (deferred):**

- Seniority/title filtering — plumbing exists as a pass-through; rules come in phase 2.
- Scrapers for the remaining ~55 companies — added incrementally after the pattern is proven.
- Scheduled execution (cron/launchd) — added once the script is reliable.
- Desktop, Slack, or email notifications.
- Automated application submission.

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Job source | Scrape company career pages directly | User preference; avoids dependence on third-party aggregators or ATS API coverage |
| Recency detection | Snapshot diff (run-to-run) | Works uniformly whether or not a site displays a posted date |
| Fetch strategy | Hybrid: `requests` for static pages, Playwright for JS-rendered pages | Many target sites are SPAs; running a browser for every site would be needlessly slow |
| Language | Python | Strongest scraping ecosystem (BeautifulSoup, Playwright) |
| Output | Console + local file | Simplest useful starting point |
| Invocation | Manual CLI | Scheduling added after reliability is established |
| Initial breadth | 4 pilot companies of mixed difficulty | Validates the framework against both easy and hard sites before scaling |

## Architecture

### Core abstraction

One scraper per company, with a uniform contract. The framework owns fetching, diffing, state, and reporting; a company module only answers "given this page's HTML, what jobs are on it?"

```python
class Scraper(Protocol):
    name: str              # "Stripe"
    career_url: str
    fetch_mode: FetchMode  # STATIC or RENDERED

    def parse(self, html: str) -> list[Job]: ...

    # Optional. Return the URL of the next page given the current page's
    # HTML and its URL, or None when there are no further pages.
    def next_page_url(self, html: str, current_url: str) -> str | None: ...
```

This keeps each company isolated: adding company #5 through #59 is a small, self-contained change that cannot break existing scrapers.

**Pagination is driven by the framework, not by individual scrapers.** The framework fetches `career_url`, calls `parse()`, then asks `next_page_url()` whether to continue, concatenating results across pages. Scrapers that omit `next_page_url` are treated as single-page. Keeping the fetch loop in the framework means retries, delays, timeouts, and rendering behavior stay consistent across companies, and each parser remains a pure HTML-to-jobs function that fixture tests can exercise offline. A page-count ceiling (default 50) prevents a malformed next-page link from causing an infinite loop.

### Data model

`Job` is the unit that gets diffed, stored, and reported:

| Field | Type | Purpose |
|---|---|---|
| `company` | `str` | Which scraper produced it |
| `job_id` | `str` | Stable identity across runs |
| `title` | `str` | Displayed; input to phase 2 filtering |
| `url` | `str` | Direct link, so the user can apply immediately |
| `location` | `str \| None` | Displayed; disambiguates duplicate titles |
| `posted_date` | `date \| None` | Populated only when the site shows it |

`job_id` derivation, in priority order:

1. The site's own job ID extracted from the job URL.
2. Fallback: a stable hash of `title + location + url`.

A stable `job_id` is critical. If it changes between runs, unchanged jobs get re-reported as new every day, making the tool useless.

### Snapshot state

One JSON file per company at `state/<company>.json`, mapping `job_id` to the job record plus `first_seen` and `last_seen` timestamps. JSON keeps state human-inspectable and debuggable, and the data volume (tens of thousands of records at most) does not justify a database.

### File layout

```
applications/
  companies.txt              # existing human-maintained company list
  requirements.txt
  README.md
  run.py                     # CLI entrypoint
  jobwatch/
    models.py                # Job, CompanyConfig, FetchMode
    fetch.py                 # fetch_static() / fetch_rendered()
    state.py                 # load/save snapshots
    diff.py                  # snapshot vs. current -> new jobs
    report.py                # console + file output
    registry.py              # company name -> scraper lookup
    filters.py               # phase 2 filtering (pass-through for now)
    scrapers/
      base.py                # Scraper protocol, shared parsing helpers
      anthropic.py
      cloudflare.py
      stripe.py
      meta.py
  state/                     # runtime snapshots (gitignored)
  output/                    # dated run logs (gitignored)
  tests/
    fixtures/                # saved HTML pages for offline parser tests
```

### CLI

```
python run.py                          # all registered companies
python run.py --company Stripe         # single company (repeatable flag)
python run.py --dry-run                # scrape and report without writing state
python run.py --verbose                # per-company diagnostics
```

`--dry-run` exists so scrapers can be developed and re-run without corrupting saved snapshots.

## Run Lifecycle

For each company, in sequence:

1. **Fetch** the career page using the company's declared fetch mode.
2. **Parse** the HTML into `Job` records.
3. **Load** the existing snapshot from `state/<company>.json`.
4. **Diff**: any `job_id` absent from the snapshot is new.
5. **Merge**: new jobs get `first_seen = now`; jobs still present get `last_seen = now`.
6. **Save** the snapshot.

After all companies finish, print a consolidated report and write it to `output/YYYY-MM-DD.json`.

Three behaviors that the correctness of this design depends on:

**First run seeds, it does not alert.** With no prior snapshot every job appears new, which would produce hundreds of meaningless results. The first run for a company records all jobs and reports `seeded N jobs, no alerts`. Real alerting begins on the second run.

**Departed jobs are retained, not pruned.** Career pages paginate and occasionally drop postings temporarily. Deleting missing jobs would cause them to be re-reported as new when they reappear, so records persist with an updated `last_seen`.

**Recency is derived from `first_seen`, not from the site.** Because runs are manual, a multi-day gap would otherwise dump several days of jobs with no indication of which are actually fresh. `first_seen` lets the report distinguish "new in the last 24 hours" from "new since your last run", and allows re-querying recent finds without re-scraping. A site-provided `posted_date`, when available, is kept as an additional signal.

## Error Handling

The most dangerous failure is not a crash — it is a parser silently returning zero jobs after a site redesign, which is indistinguishable from "no new postings." Two guards address this:

- **Zero-jobs regression:** if a company's snapshot is non-empty and the current parse yields zero jobs, treat it as a failure. Report it prominently and do **not** overwrite the snapshot; overwriting would cause the next successful run to report every job as new.
- **Implausible new-job volume:** if a run reports new jobs exceeding a configured share of the page (default: 80% of parsed jobs, on a non-seed run), flag the result as suspicious. This usually indicates the site changed its URL or ID scheme rather than a genuine hiring surge.

Additional handling:

- Each company runs inside its own error boundary, so one broken site cannot abort the run. Failures are collected and summarized at the end with a non-zero exit code.
- HTTP requests use explicit timeouts and limited retries with exponential backoff.
- Requests send a realistic user-agent, and a short delay separates companies to remain polite.
- HTTP 403 and 429 are reported as `blocked`, distinctly from "no jobs found", so anti-bot measures are visible rather than silent.
- Playwright fetches wait for a company-specified selector rather than a fixed sleep, and time out with a clear error.

## Testing

**Parsers are tested offline against saved HTML fixtures.** Each company parser has a real captured page under `tests/fixtures/<company>.html`, with assertions on parsed job count and the fields of a known job. This makes parser tests fast, deterministic, and free of network flakiness and rate limits.

**Diff and state logic are unit-tested with synthetic jobs**, covering the cases that cause real-world misbehavior:

- First run seeds all jobs and produces no alerts.
- An identical second run produces zero new jobs.
- A genuinely new job is reported exactly once.
- A job that disappears and later reappears is not re-reported.
- A parse returning zero jobs against a non-empty snapshot fails and leaves state untouched.

**Live site verification is a manual step**, not a unit test: `python run.py --company X --dry-run` confirms selectors still match the real page.

## Phase 2: Role Filtering

Filtering runs at report time only and never touches the state layer. Snapshots record every job a company posts, regardless of fit.

This ordering matters: if filtering happened before persistence, later widening the criteria (for example, deciding to include Staff-level roles) would find that those jobs were never recorded and are permanently invisible. Report-time filtering also means a filter bug cannot corrupt stored history.

The planned filter is config-driven title matching: an allow-list of desired patterns, a deny-list for noise (management, internships, non-engineering roles), and a parsed seniority level used to group report output. `filters.py` ships in phase 1 as a pass-through so wiring it up later is a small change.

## Pilot Companies

Chosen for a deliberate spread of difficulty, so the framework is validated against both extremes:

| Company | Expected difficulty |
|---|---|
| Anthropic | Likely a simple hosted job board; static fetch |
| Cloudflare | Likely a simple hosted job board; static fetch |
| Stripe | Custom but structured page |
| Meta | JS-rendered SPA; requires Playwright |

Difficulty expectations are unverified. Implementation begins with a recon pass on each of the four pages to confirm actual page structure, pagination behavior, and fetch mode before any parser is written.

## Success Criteria

1. Two consecutive runs with no site changes report zero new jobs.
2. A job newly posted by a pilot company appears in the next run's report, with a working direct link.
3. A deliberately broken parser (bad selector) is reported as a failure and leaves its snapshot unmodified.
4. One company failing does not prevent the other three from reporting.
5. Adding a new company requires only a new scraper module and a registry entry.
