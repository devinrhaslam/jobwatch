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

Every run prints progress to stderr as it goes, so a multi-minute run is
legible rather than silent — the report itself goes to stdout, so piping is
unaffected:

```
[  1/105] Adobe          ........... seeded 810 (24.1s)
[  2/105] Adyen          . read 221 (0.8s)
[  3/105] Microsoft      .... read 40, 15 new (4.6s)
Scraped 105 companies in 341s
Classifying 32 new jobs... kept 6 of 32 (11.4s)
```

One dot per network request, so a company making 185 of them looks busy rather
than hung, and the slow ones are obvious at a glance. **`read N` is what that
run fetched, not the size of the board** — most companies stop paginating at the
first page with no unseen ids, which is why Microsoft shows 40 against ~1,850
postings.

`--verbose` adds a line per job the role filter dropped, with the reason. Worth
using for the first few runs to check the filter against your own judgement.

A non-zero exit code means at least one company returned `FAILED` or
`BLOCKED`. Check the report for details.

On a normal (non-dry-run) run, a dated JSON report is written under
`output/YYYY-MM-DD.json`. Running again the same day **merges** into that file
rather than replacing it: a company in the new run replaces its earlier entry,
and every other company the day has already seen is kept. Without that, a later
`--company X` run would reduce the whole day's record to one company, which is
how one full run's 807 jobs were lost.

### First run vs. daily runs (seeding)

The first run for any company is a **seed run**. It fetches every current
listing, saves them all to `state/<company>.json`, and reports
`seeded N jobs, no alerts` — nothing is flagged as new. Board sizes vary
widely: SpaceX seeds ~2,100 jobs, Anduril ~2,170, Amazon ~2,060, NVIDIA ~2,050,
Microsoft ~1,850, Capital One ~1,760, Tesla ~1,350, Adobe ~810, OpenAI ~740,
Stripe ~540, ServiceNow ~460, eBay ~440, Datadog ~430, Intuit ~390, Okta ~350,
Palantir ~300, CoreWeave ~295, Disney ~770, Mastercard ~1,120, Atlassian ~230,
Shopify ~109, Klarna ~100, PayPal ~88, LinkedIn ~46, Etsy ~35, Linear ~24, and
of the newest: Goldman Sachs ~890, Visa ~775, Rivian ~630, Bloomberg ~405,
Unity ~124, Walmart Global Tech ~684. Seeding all 105 companies stores roughly
41,700 listings.

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
in one request, so those 66 companies finish in about 95 seconds. Workday caps
a page at 20 results, so seeding its eleven companies costs ~510 requests and
several minutes — but results come newest-first, and the engine stops
paginating at the first page with no unseen ids, so a routine run reads one or
two pages per company.

The PCSX boards (Microsoft, PayPal) cap a page at 10 results and ignore every
page-size parameter, so Microsoft's seed costs ~185 requests and a few minutes;
PayPal's is 88 postings and finishes at once. Its results are newest-first,
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
| `BLOCKED` | Site refused the request (403, 406, 429, 451) — rate-limited or bot-detected. A 429 is retried first, honouring `Retry-After` when the server sends one, so this status means it was still refusing after those attempts. |
| `SUSPICIOUS` | More than 80% of current jobs look "new" against an existing snapshot, suggesting the site changed its job ID or URL scheme. New jobs are listed but the snapshot is **not** updated until the scraper is fixed. |

`FAILED` and `BLOCKED` are deliberately loud: a company cannot silently go
dark. Fix the scraper or retry later rather than ignoring a failed section.

## Currently tracked companies

262 companies are watched: 235 through eighteen shared platform scrapers,
plus 27 bespoke portals. That is every company in `companies.txt` — nothing on
the list is unbuilt.

| Source | Companies | Fetch mode |
|--------|-----------|------------|
| Greenhouse board API | Adyen, Affirm, Agility Robotics, Airbnb, Airtable, Anduril, Anthropic, Apptronik, Archer Aviation, Asana, Astranis, Beta Technologies, BILL, Block, Brex, Carvana, Chainguard, Chime, ClickHouse, Cloudflare, Cockroach Labs, Coinbase, CoreWeave, Coupang, Cresta, Cribl, Databricks, Datadog, Discord, DoorDash, Doximity, Dropbox, Duolingo, Elastic, Epic Games, Faire, Fastly, Figma, Figure AI, Fireblocks, Fivetran, Flexport, GitLab, Glean, Gong, Grafana Labs, Gusto, Honeycomb, HubSpot, Instacart, Jane Street, JFrog, Klaviyo, Kodiak Robotics, LaunchDarkly, Lyft, Marqeta, Mercury, MongoDB, Monzo, Motional, Navan, Neo4j, Netlify, Netskope, Neuralink, Nuro, Okta, Oura, Pinterest, Planet Labs, Postman, Pure Storage, Reddit, Relativity Space, Riot Games, Ripple, Robinhood, Roblox, Rocket Lab, Rockstar Games, Rubrik, Samsara, Scale AI, Scopely, SHEIN, Skild AI, SoFi, Sony Interactive Entertainment, Sourcegraph, SpaceX, Stripe, StubHub, Tailscale, Take-Two Interactive, Toast, Together AI, Twilio, Twitch, Vannevar Labs, Varda Space Industries, Vast Space, Vercel, Verkada, Warp, Waymo, Wayve, Wiz, World Labs, xAI, Zipline, Zscaler | static HTTP |
| Ashby posting API | 1X Technologies, Abridge, Airwallex, Alchemy, Applied Intuition, Baseten, Bumble, Cerebras, Chainalysis, Checkout.com, Cognition, Cohere, Confluent, Crusoe, Cursor, Decagon, Docker, ElevenLabs, Fireworks AI, Grammarly, Harvey, Hims & Hers, Hinge Health, Kraken, Lambda, LangChain, Linear, Luma AI, Mercor, Miro, Mistral AI, Modal, Modern Treasury, monday.com, Niantic, Notion, Nubank, OpenAI, OpenEvidence, Perplexity, Physical Intelligence, Pinecone, Plaid, Poolside, Ramp, Redis, Reflection AI, Replit, Runway, Saronic, Sentry, Sierra, Skydio, Snowflake, Strava, Substack, Suno, Supercell, Synthesia, Temporal, Thinking Machines Lab, Vanta, Weaviate, Whoop, WorkOS, Writer | static HTTP |
| Ashby board GraphQL | Whatnot | JSON POST |
| Lever postings API | Match Group, Palantir, Shield AI, Spotify, Veeva Systems, Zoox | static HTTP |
| Workday CXS API | Adobe, Autodesk, Blue Origin, Boston Dynamics, Broadcom, Cadence Design Systems, Capital One, Chewy, CrowdStrike, eBay, Etsy, Expedia, Marvell Technology, Mastercard, Nike, NVIDIA, Palo Alto Networks, Remitly, Salesforce, Snyk, Target, Tempus AI, Unity, Visa, Workday, Zillow | JSON POST |
| Phenom career site | Circle | JSON POST |
| Avature sitemap | Electronic Arts, Synopsys | static HTTP |
| Workable widget API | Hugging Face | static HTTP |
| iCIMS sitemap + JobPosting | Joby Aviation | static HTTP |
| Comeet careers API | VAST Data | static HTTP |
| ClearCompany careers API | Firefly Aerospace | static HTTP |
| Pinpoint postings feed | Impulse Space | static HTTP |
| iCIMS career site | AMD, Booking.com | static HTTP |
| Deel job board (sitemap + JSON-LD) | Deel, Klarna | static HTTP |
| Eightfold | Netflix | static HTTP |
| SmartRecruiters | Canva, ServiceNow, Wise | static HTTP |
| Oracle Recruiting Cloud | American Express, Uber | static HTTP |
| Bespoke portal | Amazon, Apple, Atlassian, Bloomberg, GitHub, Goldman Sachs, Google, Klarna, LinkedIn, Retool, Rivian, SentinelOne, Shopify, Snap, Two Sigma | static HTTP |
| Bespoke portal | Aurora, Valve, Zed, Zoom | static HTTP |
| Bespoke portal | Revolut | rendered (Firefox) |
| Bespoke portal | Dynatrace | JSON POST |
| Bespoke portal | Wayfair | static HTTP, JSON via an Accept header |
| Bespoke portal | Walmart Global Tech | JSON POST |
| Radancy RSS feed | Arm, Disney, Intuit | static HTTP |
| Eightfold PCSX | Microsoft, PayPal, Qualcomm | static HTTP |
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

### Thin listings: per-job enrichment

Some boards have a listing that is a stable published interface but carries
almost no data — a sitemap of bare ids — while each posting's own page is
richly structured. A scraper for one of those implements two more methods:

- `detail_url(job)` — the page to read for this job, or `None` to skip it.
- `parse_detail(payload, job)` — return `job` enriched from that page.

The engine calls these **after the diff and before the snapshot is written**,
so only genuinely new postings cost a request, and both the saved record and
`run.py`'s role filter see the real title rather than a placeholder. A seed run
enriches the whole board once; every run after that pays for the day's postings
alone — Klarna's seed is 100 detail fetches and about 70 seconds, and its
routine run is a single request.

Enrichment is best-effort: a detail page that fails to fetch or parse leaves
that job with its listing data and the run continues, because a thin title plus
a working link still beats losing the diff. `max_enrichment_fetches` caps the
per-run count so a board that suddenly reports hundreds of new jobs cannot turn
into hundreds of requests.

## Scaling to the rest

`tools/probe_ats.py` identifies which platform each company in `companies.txt`
uses. As of 2026-08-11, all 262 listed companies are built.

### robots.txt is not a reason to skip a board

Reading a public job posting with a script is the same act as reading it in a
browser, and robots.txt is a convention with no legal force — *hiQ v. LinkedIn*
found that scraping public data does not violate the CFAA. Three companies were
skipped on this basis and all three were wrong, in the same way: the disallowing
host was not the one serving the board.

- **AMD** and **Booking.com** were skipped over `Disallow: /` on
  careers-amd.icims.com and internal-workingatbooking.icims.com. Those hosts are
  the *application* step. Reading the 403 body says "Your IP address is not on a
  trusted network" — an internal IP allowlist, not a crawler rule. Both boards
  are on the companies' own sites, which allow everything.
- **Arm** was skipped for the same reason and is on Radancy, a platform already
  supported here; it was a one-line config add.

What is still honoured: a `Crawl-delay` is respected (AMD, Booking.com and Zoom
all set five seconds), and bot-protection circumvention stays off the table —
no fingerprint spoofing, no `navigator.webdriver` masking. Where a site
challenges one browser engine and not another, using the other engine is not a
bypass: Revolut serves headless Firefox normally and challenges Chromium, which
is the same engine-specific check Tesla has.

Findings from the round that re-tested the last three:

Two of the three were wrong, which is now nine "impossible" boards and nine
times wrong. Both were missed the same way: **the careers path was not
`/careers`, and the slug was not derivable from the name.**

- **Skild AI is on Greenhouse**, board `skildai-careers`, 60 postings. Its page
  is `/career`, singular — `/careers` 404s, and that 404 was the whole basis for
  "no board". The board id is in neither the HTML nor a sitemap (it publishes
  none); the page ships `Current Openings • 00` and `Loading...`, and the id
  appears only inside `/_next/static/chunks/app/career/page-*.js`, which
  `fetch`es the Greenhouse API directly from the browser. Reading the page's own
  JS chunk is cheaper than launching a browser for resource timings and found it
  in one request.
- **No name-derived slug reaches `skildai-careers`.** `probe_ats.py` joins its
  suffixes without a separator, so it tries `skildaicareers` and `skild-aicareers`
  and never the hyphenated-compact form. Worth adding if another board turns up
  the same way; one instance is not yet a pattern.
- **Hims & Hers is on Ashby**, board `hims-and-hers`, 102 postings including a
  dozen software engineering roles. The slug spells out the ampersand, which no
  guess built: dropping `&` gives `hims-hers`, and that 404s. The link is on
  `hims.com/careers-professionals` — a path a subpath scan would have to guess —
  and the only reason it was found is that the page's outbound links were read
  rather than its paths guessed. The 2,433-entry sitemap really does omit it.
- **The same page family links a second Ashby board, `you-health`**, which is
  the affiliated clinician network rather than the company: five 1099 telehealth
  physician and nurse-practitioner roles, no engineering. Tracking it would file
  a separate company's postings under this one, so only `hims-and-hers` is read.
- **Groq's board is live, readable, and empty.** `jobs.gem.com/groq` is a Gem
  job board that renders "Open positions (0)". Its API —
  `POST jobs.gem.com/api/public/graphql/batch`, operation `JobBoardList`,
  `boardId: "groq"` — answers a plain HTTP request with no browser, no auth and
  no captcha, returning `{"jobPostings": []}`. The department filters behind it
  are fully populated (Compiler, Assembler, GROQ API, Engineering Research and
  ~16 more) and every one reports `count: 0`. So the earlier "no public board"
  was wrong about the board and right about the postings: groq.com/careers does
  redirect to /company, and the only careers link on that page is a Gem
  expression-of-interest form.
- **Groq was dropped from `companies.txt` rather than registered.** A board that
  parses to zero jobs is `FAILED` by design — a zero-job read is
  indistinguishable from a broken parser, and an empty seed would silence the
  company permanently — so registering it would have failed every run and taken
  the process exit code with it. Leaving it listed-but-unbuilt was the other
  option and it is worse: it reads as a backlog item when the work is done and
  the answer is "no openings". Watching resumes by re-adding the line; the
  precondition is that GraphQL call returning a non-empty `jobPostings`, at
  which point Groq is one small `gem.py` module — one request, no pagination
  seen yet.

Findings from the round that fixed the two companies failing on 2026-08-11:

- **A front end that "can only lose data" can outlive the system behind it.**
  Circle was read from its Workday tenant on the reasoning recorded above:
  Phenom sits in front of it and carries no posting URL of its own, so reading
  the tenant skipped a layer that could only subtract. That tenant has since
  been retired — every site name on `circle.wd1` answers 401, and its posting
  pages redirect to `community.workday.com/maintenance-page`, so every link it
  ever produced is dead — and the layer that could only lose data is now the
  only one serving any. The reasoning was right when written; what changed is
  which system still exists.
- **A listing with no posting URL can still yield one.** Phenom's records carry
  a `jobSeqNo`, and the careers site routes on it: the slug after it is
  decorative, so a title edited later still resolves, and a retired posting
  answers 410 rather than silently rendering the whole listing — the property
  the Stripe and Pinterest links were changed to get. The URLs built this way
  were checked against the sitemap `robots.txt` publishes and all 74 matched
  byte for byte, which is the site's own statement of the canonical link.
- **Circle's board is not ordered by recency**, and `sortBy` is decorative —
  `most_recent`, `relevance` and an empty string all return the same order, and
  it is not `postedDate` order. So it sets `paginate_fully`, like Netflix. At 74
  postings and a page size of 100 that costs one request.
- **Nine of Circle's ids changed shape in the move**, because Workday and Phenom
  suffix the same requisition differently (`JR100013-1` against `JR100013-EG`,
  and `JR100755-1` against a bare `JR100755`). Those nine were reported as new
  once. The base requisition number is the same in both, so keying on that would
  have suppressed them — but it would also collapse two genuinely distinct
  postings that happen to share a requisition, which is the worse failure.
- **A 200 with an empty body is not a successful fetch, and it is worth
  retrying separately from an error.** EA's Avature sitemap answers 200 with a
  zero-length body to *half* of all requests and the full 635 KB board to the
  rest, from the same URL seconds apart, with identical headers; the empties
  arrive in bursts of up to three. Nothing about the request changes it —
  `Accept-Encoding: identity`, a fresh session and an explicit XML `Accept`
  header all see the same coin flip. Sharing the three-attempt budget a 5xx gets
  still failed a quarter of runs, so an empty body has its own budget of eight
  attempts a second apart. That is safe in a way retrying a 403 is not: every
  one of these responses is a 200 from a host refusing nothing, so there is no
  throttle to keep alive. Measured after the change: ten runs, ten successes.

Findings from the round that re-tested what had been written off:

- **Valve's whole board is on its front page**, as `?job_id=<n>` links — the id
  is a query parameter, not a path segment, which is why every scan for
  path-shaped job URLs reported nothing and `/en/jobs` redirecting to `/en/`
  looked like a retired page. The "Search Jobs" box is a client-side filter over
  links already in the HTML, so nothing needs rendering, and there is no
  robots.txt at all. 27 postings, eight of them engineering.


Four of the six companies recorded as having "no public board" turned out to
have one. The label was wrong, and each was wrong for a different reason worth
remembering:

- **Zoom** was called browser-only because its job *pages* answer 202 with an
  empty body. Its sitemap is served normally and robots.txt publishes it by
  name, so the board never needed a browser — only the postings do, and those
  are not what a scraper reads. The cost is a lossy title: Zoom's slug runs
  title and location together with no separator.
- **Impulse Space** was rejected for having no per-job URL, on the strength of a
  `__NEXT_DATA__` block that turned out to be a department preview of 23 roles.
  The real board is Pinpoint — `impulsespace.pinpointhq.com`, 163 postings — and
  the link to it sits below the fold, filtered out by a link scan that only kept
  job-shaped URLs.
- **Deel** hides its whole board in escaped JSON inside the careers page HTML,
  which is why a scan for `__NEXT_DATA__` and for ATS *hostnames* both missed
  it: the string "ashby" appears 1,108 times in that page and never as a host.
  It is hosted on Deel's own job-board product, which the Klarna scraper already
  read — so `klarna.py` became the parameterised `deelboard.py` and Deel is a
  config line. Klarna's parsed output was checked to be identical before and
  after the migration.
- **Archer Aviation** was on Greenhouse under `archer56` all along.

The two that survived re-testing — Groq and Hims & Hers — have careers pages
that 404 or redirect away with no openings anywhere on them, which is a
different claim from "not found". **Hims & Hers was still wrong**, and Skild AI
with it; see the round below.

Findings from the eleventh round on the own-hosted boards:

- **Archer Aviation was on Greenhouse the whole time**, board `archer56`. Its
  careers page is a 9 KB shell that fetches the board client-side, so nothing
  in the HTML or the sitemap names it — only the browser's resource timings do.
  A numeric suffix again, like `sourcegraph91`: no name-derived guess reaches
  either.
- **Some of the remainder have no public board to find.** Groq's /careers now
  redirects to /company with no openings anywhere on it; Hims & Hers answers 404
  on /careers and publishes no careers URL in a 2,433-entry sitemap. Those are
  not scraping problems. *(Both claims were tested again later and both were
  wrong about the board's existence — see "the round that re-tested the last
  three". Every sentence here is factually true and the conclusion drawn from
  them was still false.)*
- **Two hosts refuse this machine outright**: MercadoLibre's careers host and
  Revolut's both fail to connect or time out even through a browser, so neither
  can be characterised from here at all.

Findings from the tenth round on the own-hosted boards:

- **Firefly Aerospace is on ClearCompany**, whose API host serves an empty
  robots.txt — but its portal host, `<company>.clearcompany.com`, answers
  `Disallow: /` and serves an empty shell anyway. So the API is read and the
  posting URL reported is Firefly's own `?jobId=` page, which was *checked in a
  browser* to render the job's title, description and apply button rather than
  the whole list. That check is the difference between this and Zipline.
- **Zed's board is two roles and needs nothing clever**: server-rendered links
  on its own site, robots wide open, titles in the anchor text. Its slug and
  title disagree ("product-designer" is "Product Design Engineer"), which is why
  the anchor text is read rather than the slug prettified.

Findings from the ninth round on the own-hosted boards:

- **Weights & Biases was dropped**: its careers page's own "VIEW ALL ROLES"
  button goes to coreweave.com, which acquired it, and CoreWeave's board —
  already tracked — carries roles titled "… - Weights & Biases". The fourth
  company absorbed into one already watched, after dbt Labs, CyberArk and
  HashiCorp.
- **Aurora is Ashby underneath but unreachable through it.** Every `applyLink`
  carries an `ashby_jid`, yet Ashby's posting API is opt-in and switched off for
  this org, so all seven slug guesses 404. Its own `/api/jobs-index` answers the
  whole board instead, and the listing's `/careers/<id>` links are used rather
  than the applyLink, which puts the id in a query parameter.
- **A date field with few distinct values is not automatically fake.** Aurora's
  `publishedDate` takes eight values across 71 postings — but they span January
  to August rather than clustering at the fetch, because Aurora posts in
  batches. The test asserts the span, which a crawl timestamp cannot fake.

Findings from the eighth round on the own-hosted boards:

- **A careers page can be pure marketing with the board one click further in.**
  chainalysis.com/careers carries no listing and no ATS signature at all; its
  "View open positions" link goes to /careers/job-openings/, which is plainly an
  Ashby board. Following the page's own call-to-action is worth doing before
  concluding a company hosts its own listings — it is what the earlier
  subpath scan was approximating, but a guessed path missed this one.
- **Chainalysis runs two Ashby boards**, the main one and
  `chainalysis-government-solutions` for its wholly-owned subsidiary. Only the
  main board is tracked.
- **Deel resists all of it.** Its careers page has no job links, its
  `/careers/position/` route is an empty template, and neither carries an ATS
  signature — which is notable given Deel sells an ATS and hosts Klarna's board.

Findings from the seventh round on the own-hosted boards:

- **VAST Data is on Comeet**, and the chain to it is worth recording: its
  careers page renders client-side, Comeet's own board page carries no postings
  in its HTML either, and Comeet's API rejects an untokenised request. The token
  is published in VAST's Nuxt payload — `_payload.json` — alongside the API URL,
  which is how the page itself calls it.
- **That token is a board identifier, not a credential.** It ships in the client
  payload of a public careers page and selects which public board to serve, the
  way a Greenhouse slug does. If it is rotated the run fails loudly rather than
  returning wrong data.
- **The API host is comeet.co, not the comeet.com that serves the board.** Both
  are live and only one answers the API.

Findings from the sixth round on the own-hosted boards:

- **Wayfair answers its whole board to one request** — ~380 postings, several
  MB — from the endpoint its careers page calls, and the only thing standing in
  the way is a header: without `Accept: application/json` the same URL serves
  the page's HTML. Worth trying before concluding an endpoint is not JSON.
- **Not every date field is fabricated.** Wayfair's `createdDate` has 317
  distinct values across 380 postings spanning ten months, which is a real
  publication date — unlike Dynatrace's and Joby's, which cluster at the moment
  of the fetch. The test asserts the spread rather than the presence, since
  presence is what the fake ones also have.
- **Wayfair's postings live on Avature but the Avature scraper cannot reach
  them**: that host publishes a sitemap for its event listing only, not for the
  board, so the company endpoint is the way in.

Findings from the fifth round on the own-hosted boards:

- **Read the browser's resource timings, not the page.** `performance
  .getEntriesByType('resource')` lists every URL a page actually fetched, which
  is how both Snyk and Dynatrace gave themselves up after grepping HTML and JS
  bundles had failed on each. It works where the network recorder does not.
- **Dynatrace's listing comes from a Coveo index** behind a proxy on its own
  domain, `/api/coveo/search/`. It needs no token, accepts a plain
  `{"q": "", "numberOfResults": 100}` body, pages on `firstResult`, and /api is
  not among the paths its robots.txt disallows.
- **Another fabricated timestamp.** Every Coveo result carries a `date`, and a
  whole page of them lands within four seconds and moves with each crawl: it is
  when the index last saw the posting. That is the third board whose date field
  had to be discarded, after Joby's per-request `datePosted` and Greenhouse's
  `updated_at`.

Findings from the fourth round on the own-hosted boards:

- **Navan's board is still under its former name, TripActions** — 208 postings,
  and its `absolute_url` names navan.com, so there is no doubt whose it is. The
  same class of miss as Veeva: a slug that does not derive from the listed name.
- **`vast` is Vast Space, not VAST Data.** "Billions of people living and
  thriving in space" is not a storage company. Added as its own company since it
  belongs with Varda, Impulse and Astranis; VAST Data is still unbuilt.
- **Snyk is on Workday**, tenant `snyk/wd103/External`, discovered only through
  snyk.io's own `/api/next/jobs`, whose records carry Workday URLs. The tenant
  hunt had missed it because that tenant's robots.txt says `Disallow: /External/`
  rather than the `Allow: /<Site>/` the hunt keys on.
- **Four tenants already registered disallow their own board path**: Chewy,
  eBay, Nike and Palo Alto Networks, now joined by Snyk. The CXS endpoint the
  scraper reads lives under `/wday/` and is not covered by those rules, and the
  disallowed paths are only ever linked, never fetched. That is a different case
  from AMD, Arm and Booking.com, whose hosts answer `Disallow: /` outright and
  are left unbuilt. Worth a deliberate decision rather than an accident.

Findings from the third round on the own-hosted boards:

- **Veeva was a Lever board all along**, under the bare slug `veeva` — 805
  postings. Nothing on careers.veeva.com says so: it is a WordPress site that
  renders the board itself, and the only trace is JavaScript building links out
  of a `lever_id`. `probe_ats.py` never reached it because the listed name is
  "Veeva Systems", so every slug it derived carried the "systems".
- **SentinelOne posts to Greenhouse but never names the board.** The slug is
  absent from the page, from its network traffic, and from six guesses. Its own
  rendered listing is complete and server-side, though, and its `?gh_jid=` links
  do open the posting — verified over plain HTTP, `<title>` and all — so it is
  read from its own HTML instead. See `sentinelone.py`.
- **A careers site built on WordPress is worth a `/wp-json/` probe** before
  anything else; Veeva's returned no job routes, which is what sent the search
  to its JavaScript and found the `lever_id`.

Findings from the second round on the own-hosted boards:

- **A Workday tenant's robots.txt names its site.** `probe_ats.py` never checks
  Workday because the CXS endpoint needs tenant, cluster *and* site — but the
  tenant publishes the third part:

      Sitemap: https://circle.wd1.myworkdayjobs.com/Circle/siteMap.xml
      Allow: /Circle/

  So guessing tenant and cluster is enough, and one CXS call confirms it. That
  found Blue Origin (1,388), Cadence (590), Marvell (517) and Broadcom (376) —
  none of which shows any sign of Workday on its careers page.
- **Look one page deeper than the careers landing page.** Scanning
  `/careers/jobs`, `/jobs` and similar for ATS signatures found four more where
  the landing page showed nothing: BILL and Relativity Space embed Greenhouse,
  SentinelOne renders its own list from one, and Qualcomm turned out to be on
  Eightfold PCSX with ~1,950 postings.
- **A live tenant can be a decoy.** Qualcomm has a Workday tenant
  (`qualcomm/wd12/External`) whose robots.txt publishes a sitemap — and both the
  sitemap and the CXS search are empty. Its real board is the PCSX one. Finding
  a tenant is not the same as finding the board.
- **BILL joined `EMBED_FALLBACK_BOARDS`** on the same evidence as the other
  twelve: its canonical Greenhouse URL 301s to `bill.com/job?…` with
  `<title>Job</title>` and no job name anywhere on the page.

Findings from the first round on the own-hosted boards:

- **Three cheap probes settle most of them.** Embedded state (`__NEXT_DATA__`,
  Nuxt, Apollo, RSC flight data), common JSON paths on the same origin, and a
  sitemap naming per-job URLs. Across all thirty, that found a usable source for
  three and ruled out twenty-four without opening a browser.
- **Retool is the shape worth recognising**: no ATS, but the site sitemap lists
  every posting and the slug is `title--department--location`, so the listing is
  free and the page's own `<title>` supplies the real capitalisation and
  punctuation. See `retool.py`.
- **Zoom is not readable over plain HTTP.** Its careers host answers 202 with an
  empty body to every path, including job pages; its robots.txt disallows
  `/api/` and sets `Crawl-delay: 5`. The sitemap's 107 job URLs are allowed, so
  it is buildable, but only behind a browser fetch mode and at five seconds a
  page.
- **Impulse Space has no per-job URL at all.** Its 23 postings sit in
  `__NEXT_DATA__` with title, department, location and employment type, and
  nothing to link to — every job would point at the careers page, which is the
  dead-link shape `EMBED_FALLBACK_BOARDS` exists to correct. Left unbuilt rather
  than shipping links that do not open a posting.
- **A sitemap hit is not a job hit.** Blue Origin, Deel and Qualcomm matched the
  job-URL heuristic on 7–11 URLs each, all of which turned out to be category
  and help pages (`/careers/apply-assistance`).

Findings from the round that added the iCIMS scraper:

- **iCIMS permission is per tenant, not per platform.** AMD's, Arm's and
  Booking.com's hosts answer `Disallow: /`; Joby Aviation's allows everything
  but `/jobs/*referral` and publishes a 240-posting sitemap. Check robots.txt
  per tenant before concluding a platform is closed.
- **An iCIMS posting page is a shell around an iframe.** The listing sitemap
  carries only a lowercased, percent-encoded slug, and the page at that URL has
  no job content at all — the same URL with `?in_iframe=1` returns it, including
  a schema.org JobPosting with the real title and every locality.
- **Its `datePosted` is generated per request.** Every Joby posting reports
  exactly two years before the moment it was fetched, timestamps incrementing a
  couple of seconds apart down a sequential crawl. It is never reported as a
  publication date; recency comes from snapshot diffing.
- **A thin listing needs its enrichment cap raised above the board size.** A
  seed reports every posting as new, so the cap decides how much of the board
  gets a real title. At the engine's default of 120, half of Joby's 240 kept the
  lowercased slug — and a job already seen is never reported again, so it would
  have kept that placeholder permanently.
- **CyberArk and HashiCorp were dropped from `companies.txt`**, the same
  treatment dbt Labs got for Fivetran. Palo Alto Networks' Workday board already
  carries 120 CyberArk postings, identified by locations like "Office - USA -
  CyberArk Santa Clara (CA)". HashiCorp has no board of its own left — all three
  platform slugs 404 and its careers page redirects into IBM's careers search,
  whose own Avature sitemap answers 202 with an empty body. Tracking HashiCorp
  now means tracking all of IBM.

Findings from the round that added a third batch of 54 target companies:

- **A board that repeats a served page is now readable.** Target and Tempus AI
  both answer any offset past the end of their Workday board with page 1 again
  rather than a short page, so `next_page_url` never saw an exhaustion signal
  and both seeds ran to the pagination ceiling and were discarded. The engine
  now stops when a page contributes no job id it had not already collected in
  the same run, which is what a repeated page looks like. That is deliberately
  independent of `known_ids` and `paginate_fully` — both concern jobs seen on a
  *previous* run and say nothing about a board repeating itself inside one pass.
- **The same-name trap keeps recurring.** The Greenhouse board `warp` is Warp
  the terminal; the Ashby board `warp` is an unrelated HR and payroll platform.
  That is the third instance after Runway and Gong, and reading two posting
  titles is still what catches it.
- **iCIMS is not uniformly closed.** AMD's, Arm's and Booking.com's tenants
  answer `Disallow: /`, but Joby Aviation's allows everything except one path
  and publishes a sitemap of 241 postings. The platform is not the unit of
  permission — the tenant is.
- **A live board can be an empty one.** Chronosphere's Ashby board and Safe
  Superintelligence's both answered 200 with zero postings on the posting API
  and on the GraphQL fallback. Registering either would produce a permanent
  FAILED, since a seed of zero jobs is refused by design. Both were dropped from
  `companies.txt` rather than left as permanent gaps in the coverage count.

Findings from the round that chased the boards with no ATS signature:

- **Most of the remainder were slug problems, not platform problems.** Trying
  hand-written aliases — legal names, brand names, domains — against the APIs
  already supported found five: `gongio` (not `gong`, which is a different
  company), `taketwo`, `flyzipline`, and the domain-style `checkout.com` and
  `monday.com`. Worth exhausting before concluding a board needs a new scraper.
- **A parent and its studio can run separate boards.** Take-Two's own board
  carries 33 postings and Rockstar Games' another 74, with no overlap, so
  Rockstar is tracked as its own company.
- **Avature portals need not be on avature.net.** EA runs one on jobs.ea.com,
  which is why `avature.py` keys on a whole sitemap URL rather than a tenant
  name. Its sitemap index lists eleven locale sitemaps carrying the identical
  361 postings, so one locale is the whole board and following the index would
  report every job eleven times.
- **A canonical Greenhouse URL can still be a dead link, and twelve boards were.**
  `_posting_url` already refuses an `absolute_url` carrying the id only in a
  query parameter. What these boards add is that their *canonical* URL 301s to
  that same page, so the fallback lands on the dead end it was avoiding and both
  URLs answer a healthy 200. A sweep of every Greenhouse board — one paced
  request each, asserting the job's title appears on the page it opens — found
  twelve, against two found by sampling. Greenhouse's standalone embed view
  (`/embed/job_app?for=<slug>&token=<id>`) is never redirected and rendered the
  posting on every board tried, so it is one general remedy rather than twelve
  bespoke ones; see `EMBED_FALLBACK_BOARDS`.
- **A plain-HTTP title check has false positives.** Duolingo and HubSpot failed
  it too, but both put the id in the path and Duolingo was confirmed in a
  browser to render the posting — the check was defeated by client-side
  rendering, not by a dead link. A failed assertion is a reason to open the page
  in a browser, not to rewrite the URL.
- **Scanning JS bundles for an ATS host does not work.** Sixteen careers pages
  were fetched along with their script bundles and not one named its endpoint.
  Driving a browser and reading the actual network requests did work, and showed
  why: sites like Retool have no ATS at all and render job pages on their own
  domain, so there is no third-party host to find.

Findings from the round that added the Avature and Workable scrapers:

- **Phenom is a front end, not an ATS.** Chewy's and Circle's careers sites are
  Phenom, whose search API carries no posting URL at all — only an `applyUrl`
  pointing back at the Workday tenant behind it. Both are plain Workday tenants
  (`chewy/wd5/External`, `circle/wd1/Circle`) whose job counts match the Phenom
  site exactly, so they are read there instead and no Phenom scraper exists.
  Worth checking for the same shape before writing a scraper for any careers
  site whose listings look like a skin. (Circle has since moved back to Phenom
  — see "the round that fixed the two companies failing on 2026-08-11" below.
  Chewy's Workday tenant is still live and Chewy is still read there.)
- **iCIMS is closed by robots.txt.** `careers-amd.icims.com`,
  `experienced-arm.icims.com`, `earlycareers-arm.icims.com` and
  `internal-workingatbooking.icims.com` all answer `Disallow: /`. AMD, Arm and
  Booking.com therefore need an allowed source on their own domains rather than
  an iCIMS scraper.
- **Avature publishes a sitemap and says so.** Synopsys' robots.txt allows
  `/careers` and names the sitemap, the same basis the Bloomberg scraper already
  relies on. Synopsys repeats the requisition id at the end of the URL slug, so
  the title has to drop it; Bloomberg's slugs do not.

Findings from the round that added a second batch of 56 target companies:

- **A live board under the obvious slug can be the wrong company entirely.**
  The Ashby board `runway` belongs to Runway the business planning platform;
  the AI video company is `runway-ml`. Both are live, so a slug guess finds the
  wrong one first and nothing about the response says so. Likewise the
  SmartRecruiters board `gong` carries journalism internships, not Gong the
  revenue-intelligence company. Reading two posting titles is what catches
  this, and it is worth doing for every name that is also an ordinary word —
  Lambda, Modal, Mercury, Ripple, Miro and Suno all had to be checked.
- **Two live boards under the same slug means a migration.** Bumble is on both
  Lever and Ashby as `bumbleinc`; the Ashby board is a week fresher, so it is
  the one that is actually being posted to.
- **Corporate splits move a name to a different company.** nianticlabs.com
  now redirects to Scopely's board — the games division was sold — and the
  company still called Niantic is Niantic Spatial, on its own Ashby board.
  cyberark.com/careers redirects into Palo Alto Networks, which already has a
  scraper here.

Findings from the round that added 53 target companies:

- **Slug guessing finds a board; only the postings identify the company.**
  `americanexpressglobal` is a live SmartRecruiters board, but its fourteen
  postings are Travel Counselor roles: it belongs to Amex GBT, the travel
  business spun out as its own public company. American Express itself is on an
  Oracle tenant that the same careers page also links.
- **Going the other way finds what slug guessing cannot.** Loading each careers
  page and reading which ATS host it points at identified nine more boards that
  no name-derived slug would reach — six Workday tenants, plus Ashby boards
  registered as `mistral.ai` (a domain, like Kraken's) and `ThinkingMachines`
  (CamelCase, and the posting API is case-sensitive).
- **dbt Labs is Fivetran.** The two merged; getdbt.com/careers now renders the
  Fivetran Greenhouse board, and the job ids on it are Fivetran's. Watching both
  names would report every posting twice, so dbt Labs was dropped from
  `companies.txt` rather than given a scraper.
- **A board can paginate without ever ending.** Target's Workday tenant serves
  page 1 again past the end of the board instead of the short page every other
  tenant gives, so a seed runs to the pagination ceiling and is discarded. It is
  left out until there is a stop rule for a board that repeats a page it already
  served.
- **Two live boards can both be correct.** ClickHouse serves the same 167
  postings on Greenhouse and Ashby with identical publish timestamps, and Shield
  AI is on both Lever and Ashby. ClickHouse was settled arbitrarily; Shield AI
  by which board shield.ai/careers actually links to.

Still unbuilt, twenty-one of them, in three groups — **as of that round only.**
Every one has since been built or dropped, and two of the names below were
wrong about their own premise: Skild AI turned out to be on Greenhouse and
Wayfair's board was reachable after all. Read this list as a record of what was
believed then, not as the current backlog; the "Currently tracked companies"
table is the live answer.

- **Closed by robots.txt.** AMD, Arm and Booking.com are on iCIMS hosts that
  answer `Disallow: /`, so each needs an allowed source on its own domain.
- **Absorbed into a company already tracked.** HashiCorp redirects to IBM's
  careers search and CyberArk into Palo Alto Networks. Neither needs its own
  scraper so much as a decision about whether the parent's board covers it.
- **No third-party ATS to find.** Aurora, Blue Origin, Broadcom, Cadence Design
  Systems, Deel, Dynatrace, Groq, MercadoLibre, Retool, Revolut, Skild AI,
  Snyk, Valve, Wayfair and Weights & Biases host their own listings. Retool was
  checked in a browser and renders job pages on its own domain with no ATS
  request at all, so these are bespoke scrapers, one per company, not a missing
  platform module. Revolut answers 403 to plain HTTP and Cadence refuses the
  connection, so those two need a browser before anything else.

From the third batch, still unbuilt: Joby Aviation is on an iCIMS tenant that
*does* allow crawling and publishes a 241-posting sitemap, so it is one small
module away. Chronosphere and Safe Superintelligence have live but empty Ashby
boards. Archer Aviation, BILL, Chainalysis, Firefly Aerospace, Hims & Hers,
Impulse Space, Marvell Technology, Navan, Qualcomm, Relativity Space,
SentinelOne, VAST Data, Veeva Systems, Zed and Zoom showed no ATS signature on
their careers landing page.

Findings from the earlier round, recorded so they are not re-derived:

- **A board name is not always a slug.** Grammarly renamed itself Superhuman in
  2025, and its Ashby board is registered under the legal entity with spaces
  intact — `Superhuman Platform Inc`. Every slug guess (`grammarly`,
  `superhuman`, `superhumanhq`) 404s. Kraken's is the domain, `kraken.com`.
- **A wrong Workday cluster answers 500, a wrong tenant 404.** That is what
  found Visa (`visa/wd5/Visa`, 775 postings) after `usa.visa.com/careers` turned
  out to be a 403/404 dead end. Unity's tenant is `unitytech`, not `unity`.
- **Klarna does not run its own board** — klarna.com/careers links out to Deel,
  whose robots.txt disallows `/api/`. Of the three readable sources, the board
  page's React Server Components payload has everything in one request, but it
  is an internal Next.js format with no stability contract. This scraper uses
  the two published ones instead: the per-org sitemap that robots.txt documents
  by name (detection — it carries bare UUIDs and nothing else), plus the
  schema.org `JobPosting` JSON-LD on each posting page (title, location, a real
  `datePosted`), fetched only for new postings. See "Thin listings" above.
- **Goldman Sachs leaves GraphQL introspection enabled**, so its query was
  derived from the schema rather than guessed. Its `totalCount` is not a stop
  condition: it reports 1,096 while pagination yields 896 rows and then a short
  page. `INTERNAL_MOBILITY` and `CAMPUS` are excluded — internal-only and
  student roles.
- **Bloomberg has two hosts and only one is readable.** `careers.bloomberg.com`
  answers 403 to plain HTTP and serves an "Are you a robot?" challenge to a real
  browser; that challenge is not something to work around. Its actual ATS is
  Avature on its own host, which answers plain HTTP and whose robots.txt
  explicitly allows `/careers` and publishes the sitemap the scraper reads.

### Walmart Global Tech — the one deliberate robots.txt exception

**This is the only scraper in the project that reads a path its site's
robots.txt disallows.** `careers.walmart.com` says `Disallow: /api`, and its
search endpoint is under it. That was an explicit decision by this tool's owner,
made with the trade below in view — not an oversight, and not a change of
posture for anything else here. Every other company stays inside what its
robots.txt permits, and several (Bloomberg, Intuit, Disney, Klarna) are built
the way they are *because* of it.

The trade, recorded so it can be re-judged rather than re-derived:

- Walmart publishes **no permitted way to see only its technology roles**. The
  allowed sitemap is 15,473 bare job URLs covering the whole company — no
  titles, no categories, no `lastmod` — overwhelmingly retail store and supply
  chain.
- The compliant design was therefore "store all 15,473 ids, then fetch a detail
  page per new posting". That works, but it spends a request and a role-filter
  classification on every new store job before discarding it — and it puts
  **more** total load on Walmart than the disallowed endpoint does.
- The endpoint returns the **684 technology roles in a single request**.

Three things make it usable, all found in the site's own bundle:

- **Filters live in the query string, not the `filter` field.** The bundle
  builds `query + " brand IN [...]"` and always sends `filter: ""`.
  `areas IN [Technology]` is the same shape, and is what narrows 15,473 to 684.
- **`page` does not paginate** — page 1 returns page 0's rows.
- **The search is relevance-scored and its ordering shifts between calls**, so a
  truncated read is a *different subset* each run, and diffing two arbitrary
  subsets would report churn as new jobs. Asking for more than the board holds
  returns all of it, stably (two consecutive full reads differ by zero ids), so
  the board is always taken whole and a short response raises rather than being
  accepted as a smaller board.

Covers Walmart, Sam's Club and Vizio postings — all Walmart-owned, all carrying
`areas: ["Technology"]`.


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
tests/                  784 tests, fixture-backed parser and unit tests
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
- **Every company's new jobs are classified in one pass**, batched across
  company boundaries rather than per company. Filtering each company on its own
  cost one API call for every company with any new job at all, however few — 20
  companies with three new jobs each meant 20 sequential requests instead of
  one batch of 60. Since filtering runs after all the scraping and prints
  nothing on its own, that showed up as a run that sat silent for a quarter of
  an hour. It now prints `Classifying N new jobs...` to stderr before starting.
  For scale: scraping all 104 companies takes about 380 seconds end to end, so a
  run materially longer than that is the filter, not a scraper.
- **No scheduling** — run `run.py` manually (e.g. via cron) when you want a
  check.
- **Meta scope** — only software engineering roles, because that is what the
  configured career URL returns. Expanding to other teams means a different
  entry URL or an additional scraper.
- **Site fragility** — career pages change markup without notice. A scraper
  that worked yesterday may `FAILED` tomorrow until its selectors are updated.

## Tests

```bash
.venv/bin/pytest          # full suite (784 tests)
.venv/bin/pytest -v       # verbose
```

Parser tests use fixtures under `tests/fixtures/` and do not hit the network.
Integration-style tests for fetch and the CLI use mocks. The role filter is
tested with an injected stub classifier, so no test calls the Claude API.
