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

    # payload is the fetched page text: parsers may read it as HTML or
    # extract an embedded JSON payload from it.
    def parse(self, payload: str) -> list[Job]: ...

    # Optional. Return the URL of the next page given the current page's
    # payload and its URL, or None when there are no further pages.
    def next_page_url(self, payload: str, current_url: str) -> str | None: ...
```

This keeps each company isolated: adding company #5 through #59 is a small, self-contained change that cannot break existing scrapers.

**Pagination is driven by the framework, not by individual scrapers.** The framework fetches `career_url`, calls `parse()`, then asks `next_page_url()` whether to continue, concatenating results across pages and deduplicating by `job_id`. Scrapers that omit `next_page_url` are treated as single-page. Keeping the fetch loop in the framework means retries, delays, timeouts, and rendering behavior stay consistent across companies, and each parser remains a pure text-to-jobs function that fixture tests can exercise offline. A page-count ceiling (default 20) prevents a malformed next-page link from causing an infinite loop.

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

**Parsers are tested offline against saved HTML fixtures.** Each company parser has a real captured page under `tests/fixtures/` (`anthropic_jobs.html`, `stripe_jobs_search.html`, `cloudflare_careers.html`, `meta_jobsearch_page1.html`), with assertions on parsed job count and the fields of a known job. This makes parser tests fast, deterministic, and free of network flakiness and rate limits.

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

Recon has been completed against all four live pages, and each extraction strategy below was verified by parsing a captured page and confirming the job count and field values. Captures are stored as test fixtures under `tests/fixtures/`.

| Company | Entry URL | Fetch mode | Extraction | Verified jobs | Posted date |
|---|---|---|---|---|---|
| Anthropic | `https://www.anthropic.com/jobs` | STATIC | DOM: `a[href*="/anthropic/jobs/"]`, first two `p.caption` descendants are title and location | 400, single page | No |
| Stripe | `https://stripe.com/jobs/search` | STATIC | Embedded JSON: `"listings":[...]` array plus a `"locations":[...]` lookup table | 513, single fetch | No |
| Cloudflare | `https://www.cloudflare.com/careers/#open-roles` | RENDERED | DOM: `a[href*="boards.greenhouse.io/cloudflare/jobs/"]`, `<p>` children are title, `"Dept - City, Country"`, `"Posted <date>"` | 285 unique (570 anchors) | Yes |
| Meta | `https://www.metacareers.com/jobsearch/?sort_by_new=true&teams[0]=Software%20Engineering&page=N` | RENDERED | DOM: `a[href^="/profile/job_details/"]`, `<h3>` is title, next text node is location | 10 per page, paginated | No |

### Recon findings that shape the design

**Extraction targets are not always DOM elements.** Stripe embeds a complete JSON payload of all 513 listings in its page, making one plain HTTP fetch sufficient — no browser, no pagination. The scraper contract is therefore `parse(payload: str)`, where the payload is the fetched page text; a parser may read it as HTML or extract embedded JSON from it. This is why the contract takes text rather than a parsed DOM.

**Selectors must not depend on class names.** Anthropic ships build-hashed CSS module classes (`JobsPage-module-scss-module__8DFgsW__jobItem`) and Meta ships obfuscated atomic classes (`x1i10hfl x1qjc9v5 ...`). Both change without notice. Parsers key off href patterns and structural position (child order, tag type) instead, which are far more stable.

**Cloudflare's career page needs the `#open-roles` fragment.** Plain `https://www.cloudflare.com/careers/` renders only 6 of 285 roles ("Showing 6 of 285"), and neither scrolling nor `?page=2` loads more. With the `#open-roles` fragment, all 285 job links are present in the DOM — verified stable across repeated loads. Cloudflare also renders each job twice, so deduplication by `job_id` is required, not optional.

**Meta rejects plain HTTP.** Direct requests return HTTP 400; headless Chromium works. Meta must use RENDERED mode.

**Entry URLs may carry the site's own filters and sort order.** Meta returns only 10 jobs per page, so enumerating every posting would need hundreds of renders per run. Instead its entry URL applies Meta's own `teams[0]=Software Engineering` filter and `sort_by_new=true` sort, cutting the crawl to a few pages of relevant, newest-first results. Pages carry no overlap, and `&page=N` paginates reliably.

This source-side narrowing is distinct from the phase 2 report-time filter. Narrowing is a per-company fetch concern used where a site's volume makes full enumeration impractical; report-time filtering remains the general mechanism for role fit. Because Meta's URL filter also constrains what ever enters the snapshot, a widened filter later means Meta's snapshot re-seeds for the newly included teams — an accepted trade-off, and the reason narrowing is applied only where volume demands it.

**Cloudflare exposes real posted dates** (`Posted Jul 31, 2026`), so its `posted_date` is populated and can corroborate snapshot-derived recency. Anthropic, Stripe, and Meta expose no post date, though Meta marks some cards with a "New" badge.

### Pagination early-stop

For newest-first paginated sources such as Meta, the framework stops paginating when a page contributes no job IDs absent from the snapshot, since everything beyond that point is necessarily older and already known. Combined with the page ceiling, this keeps a routine run to one or two page fetches while still catching a large burst of new postings. On a seed run (no existing snapshot) the early-stop is skipped and the page ceiling alone applies.

## Success Criteria

1. Two consecutive runs with no site changes report zero new jobs.
2. A job newly posted by a pilot company appears in the next run's report, with a working direct link.
3. A deliberately broken parser (bad selector) is reported as a failure and leaves its snapshot unmodified.
4. One company failing does not prevent the other three from reporting.
5. Adding a new company requires only a new scraper module and a registry entry.
