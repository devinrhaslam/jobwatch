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
.venv/bin/playwright install chromium firefox
.venv/bin/pip install -e .
```

The browsers are required for the two companies not readable over plain HTTP:
Meta renders in Chromium, Tesla in Firefox (see below for why the engine
differs). Each is launched only if a company in the run needs it, so runs that
skip both (`--company` on any platform company) need no browser at all.

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
widely: SpaceX seeds ~2,100 jobs, Amazon ~2,060, NVIDIA ~2,050, Microsoft
~1,850, Tesla ~1,350, OpenAI ~740, Stripe ~540, Linear ~24. Seeding all 43
companies stores roughly 23,000 listings.

`state/tesla.json` holds ~7,570 rather than ~1,350: its first seed predated the
department filter and stored the whole board. Nothing prunes a snapshot, so
those rows simply stay, which is what makes widening the departments later a
safe change rather than a one-off flood of stale "new" jobs.

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

Microsoft caps a page at 10 results and ignores every page-size parameter, so
its seed costs ~185 requests and a few minutes. Its results are newest-first,
so a routine run still reads a page or two.

Netflix costs a further ~48 seconds because its board must be read in full
(see above) and pages are throttled. OpenAI's board is the largest single download at ~11 MB, since
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

43 companies are watched: 31 through six shared platform scrapers, plus twelve
bespoke portals. That is every company in `companies.txt` except LinkedIn — see
"Scaling to the rest" below.

| Source | Companies | Fetch mode |
|--------|-----------|------------|
| Greenhouse board API | Airbnb, Anthropic, Block, Cloudflare, Coinbase, Databricks, DoorDash, Dropbox, Figma, Jane Street, Lyft, MongoDB, Pinterest, Reddit, SpaceX, Stripe, Twitch, Vercel, Waymo | static HTTP |
| Ashby posting API | Linear, Notion, OpenAI, Plaid, Ramp, Snowflake | static HTTP |
| Workday CXS API | CrowdStrike, NVIDIA, Salesforce | JSON POST |
| Eightfold | Netflix | static HTTP |
| SmartRecruiters | Canva | static HTTP |
| Oracle Recruiting Cloud | Uber | static HTTP |
| Bespoke portal | Amazon, Apple, GitHub, Google, Microsoft, Snap, Two Sigma | static HTTP |
| Bespoke portal | ByteDance, Rippling | JSON POST |
| Bespoke portal | Hudson River Trading | form POST |
| Bespoke portal | Meta | headless browser (Chromium) |
| Bespoke portal | Tesla | headless browser (Firefox), captured API response |

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
- **A company's own careers domain is not always the right link.** Uber has
  migrated to Oracle Recruiting Cloud, and both `uber.com/careers/list/<id>`
  and `jobs.uber.com/en/jobs/<id>` now answer "the page you are looking for
  does not exist" for requisitions its board reports as live. Its links point
  at the Oracle-hosted posting instead.
- **Job links prefer the company's own posting page, but only when its URL
  actually identifies the job.** Stripe and Pinterest point Greenhouse's
  `absolute_url` at a generic listing page with the id in a query parameter;
  once a posting closes those silently render the whole search listing. Those
  fall back to the canonical `job-boards.greenhouse.io` URL, which shows an
  explicit error instead. Boards whose path names the job (Airbnb, Anthropic)
  keep their own link.
- **Pages of the same company are throttled** by `INTER_PAGE_DELAY_SECONDS`,
  which a company can raise via `inter_page_delay_seconds`. Paginated boards
  are the only place this tool makes rapid back-to-back requests, and an
  unlucky first page takes a whole company down for the run.
- **HTTP fetches share one session**, so pages of a board reuse a connection
  instead of repeating a TLS handshake. Microsoft forced this: it rate-limits
  on *new connections* rather than on request rate, answering 429 after about
  six pages fetched on fresh connections while serving 185 down a reused one.
  Slowing the request rate did not help; reusing the connection did.
- **A seed run that truncated is not saved.** It is as damaging as an empty
  seed and much quieter: it records part of a board as the whole of it, so
  every posting the run never reached is reported as new next time — hundreds
  of weeks-old jobs presented as today's. Microsoft hit exactly this, seeding
  436 of 1,849 before a 429. The company fails loudly and the next run starts
  the seed over.

**Meta and Tesla are the only companies needing a headless browser**, so a run
that skips both needs no Playwright at all.

**Tesla is read through the API its own page calls, not its markup.** The
careers page is a client-rendered app in front of a single request that returns
the entire board — all ~7,570 listings plus the lookup tables that decode them —
so `RENDERED_XHR` loads the page in a browser and keeps that response instead of
the rendered DOM. The whole board arrives in one request in about three seconds,
and a redesign of the page cannot break the parse. Listings are stored compactly
(`t` title, `l` location id) with names held once in a `lookup` table rather
than repeated across every row; job links are `…/job/<slug>-<id>`, where the
slug is decorative — the router keys on the trailing id, so a link with an
imperfect slug still resolves. Tesla exposes no posting date, so its recency
comes purely from snapshot diffing.

**Why Firefox for Tesla.** `www.tesla.com` sits behind Akamai Bot Manager, which
answers plain HTTP *and* headless Chromium with "Access Denied" before any
request reaches the board. Headless Firefox is served the page normally, so the
`browser_engine` is set per company. Nothing is disguised to achieve this — and
the one time something was, it backfired: forcing the shared Chrome user-agent
string onto Firefox made the engine claim to be a browser it wasn't, and the
filter blocked that where it had allowed an honest Firefox. `RENDERED_XHR` sends
no user-agent override for exactly that reason.

Amazon, GitHub, and Snap answer plain JSON
despite running bespoke portals; Google has no public API, so its scraper parses
server-rendered HTML, keyed on the job href pattern and structural position
rather than its build-generated class names.

**Tesla narrows by department, not at source.** Its API answers the whole board
however it is asked — the page filters client-side — so unlike Meta's and
Amazon's entry URLs, the narrowing happens in `parse()`. Tesla staffs
factories, service centres and showrooms from the same board, so keeping only
Tesla AI, Vehicle Software, and Engineering & IT cuts ~7,570 postings to
~1,350. Departments are kept rather than title keywords: the department is
Tesla's own structural label, while titles vary too much to match on, which is
the whole reason role-fit is left to the LLM. "Engineering & IT" still carries
mechanical, thermal and sales engineers, and dropping those is the report-time
filter's job. The ids are checked against their expected names on every parse,
so a renumbering fails the company loudly instead of quietly reporting Finance
roles as software. Because `merge_snapshot` only ever adds, the full 7,574-job
seed already stored stays on disk — so widening the departments later will not
flood the report with old jobs.

**Microsoft is read whole, not narrowed.** Unlike Tesla, its 1,849 postings
spread across 132 departments with a long tail, so any allowlist would quietly
drop roles rather than just noise — and at 1,849 the board is not drowning the
report in the first place. Its default sort is already `sortBy: timestamp`, so
the engine's early stop holds and a routine run reads a page or two; only the
seed pays the ~185 requests. `postedTs` is a real Unix timestamp, so its dates
are exact. Jobs are keyed on `displayJobId`, the requisition number shown on
the posting, rather than the internal id the URL is built from, since the
requisition survives a re-index of the portal.

**Amazon narrows at source**, like Meta: its board runs to tens of thousands of
postings across every function, so the entry URL applies its own
`software engineer` query with `sort=recent`. That sort is what keeps the
engine's early stop safe. **Snap exposes no posting date**, so its recency
comes purely from snapshot diffing.

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
uses. As of 2026-08-04, 43 of 44 companies are built:

| Platform | Companies | Status |
|----------|-----------|--------|
| Greenhouse | 19 | done — shared scraper |
| Workday | CrowdStrike, NVIDIA, Salesforce | done — shared scraper |
| Eightfold | Netflix | done — shared scraper |
| SmartRecruiters | Canva | done — shared scraper |
| Oracle Recruiting Cloud | Uber | done — shared scraper |
| Ashby | OpenAI (736 jobs), Snowflake, Ramp, Plaid, Notion, Linear | done — shared scraper |
| Eightfold PCSX | Microsoft | done — own module (not the shared Eightfold scraper; different host and API) |
| Bespoke, built | Amazon, Apple, ByteDance, GitHub, Google, Hudson River Trading, Rippling, Snap, Two Sigma, Meta, Tesla | own module each |

### Recon notes on the hard boards

Recorded so the next attempt starts from here rather than repeating the search.
Checked 2026-08-04.

| Company | What was found | Why it is not built |
|---|---|---|
| **Microsoft** | *Now built.* The 403 was the right error read the wrong way: `Not authorized for PCSX` names the product that **does** serve this board, just on Microsoft's own host — `apply.careers.microsoft.com/api/pcsx/search`, which needs no key, no CSRF token and no browser. The `gcsservices` host from the earlier note is gone (it now presents an `*.azureedge.net` certificate). | — |
| **Tesla** | *Now built.* The earlier "unscrapable" verdict was wrong. Akamai does serve "Access Denied" to plain HTTP and to headless Chromium, but that is a Chromium-specific check, not an edge-level IP block: **headless Firefox is served the page normally**. Its careers app calls one API returning the whole board. | — |
| **Hudson River Trading** | *Now built.* Its page does embed Greenhouse, but that board (`hrttalentcommunity`) holds 3 "Talent Community" pipeline entries — the real 72 listings come from a self-hosted WordPress plugin. | — |

**The lesson from Tesla, worth applying to the next hard board:** "blocked" was
a conclusion about one browser, not about the site. Before deciding a board
cannot be read, try the other engines — `firefox` and `webkit` are one
`browser_engine` field away — and watch the network panel for the API the page
calls, which is usually cleaner than the DOM it renders. Circumventing a bot
filter is still off the table; using a different real browser is not
circumvention, and here it was the whole answer.

Microsoft made the same point a second time: its 403 was read as a wall when it
was in fact naming the API that serves the board. Every company in
`companies.txt` is now built except LinkedIn.

**LinkedIn is excluded, and it is the one company excluded on policy rather
than difficulty.** Recon on 2026-08-04 settled it:

- Its own openings are served from `www.linkedin.com/jobs/search/?f_C=1337,…`
  — `careers.linkedin.com` is a marketing site that links there and 404s on
  `/jobs`.
- That host's `robots.txt` ends in `User-agent: *` / `Disallow: /`, and opens
  with a notice that automated access without express permission is
  prohibited, pointing at `whitelist-crawl@linkedin.com` for permission.
- There is no third-party board to read instead: `careers.linkedin.com`
  mentions no Greenhouse, Lever, Workday, Ashby, SmartRecruiters, Eightfold,
  Avature or iCIMS host. The earlier note here — that LinkedIn "matches
  Greenhouse (53 jobs) and Lever (23), neither plausibly its real volume" —
  was picking up other companies with lookalike slugs.

This is a different kind of no from the rest of this file. Tesla and Microsoft
had bot filters but no stated prohibition, so they were read with an ordinary
browser and a public API respectively. LinkedIn states one and publishes a
process for asking. So the note that "anything can be scraped" holds
technically and is not the question here.

The supported substitute is LinkedIn's own **job alerts**: saving a search
against LinkedIn's company IDs emails new postings as they appear, which is the
same day-one signal this tool exists to provide, from the mechanism LinkedIn
offers for it.

## Project layout

```
run.py                  CLI entry point
jobwatch/
  engine.py             fetch, diff, snapshot merge for one company
  fetch.py              static HTTP, POST, and Playwright rendering
                        (page markup, or a captured API response)
  diff.py               find jobs not in the snapshot
  state.py              load/save/merge per-company JSON snapshots
  report.py             format stdout report and write dated JSON
  registry.py           maps company name → scraper instance
  models.py             Job, CompanyConfig, FetchMode
  filters.py            report-time role-fit filtering via the Claude API
  scrapers/             base.py, greenhouse.py (18), ashby.py (6),
                        workday.py (3), eightfold.py (1),
                        smartrecruiters.py (1), amazon.py, github.py,
                        apple.py, bytedance.py, google.py,
                        hudsonrivertrading.py, oracle.py (1), rippling.py,
                        snap.py, twosigma.py, meta.py
state/                  per-company snapshots + filter cache (gitignored)
output/                 dated JSON reports (gitignored)
tests/                  346 tests, fixture-backed parser and unit tests
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
.venv/bin/pytest          # full suite (346 tests)
.venv/bin/pytest -v       # verbose
```

Parser tests use fixtures under `tests/fixtures/` and do not hit the network.
Integration-style tests for fetch and the CLI use mocks. The role filter is
tested with an injected stub classifier, so no test calls the Claude API.
