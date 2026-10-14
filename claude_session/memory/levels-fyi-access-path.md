---
name: levels-fyi-access-path
description: "How to read Levels.fyi comp data without an account: the .md routes its robots.txt advertises, and where the WAF line is."
metadata: 
  node_type: memory
  type: reference
  originSessionId: 9c4e8924-4036-453a-97a8-1e838aa140f6
  modified: 2026-09-20T23:42:53.625Z
---

Levels.fyi publishes an LLM-readable markdown surface and says so in its own
`robots.txt`: append `.md` to any `/companies/<slug>/salaries/...` or `/t/<job
family>/...` route. `/llms.txt` indexes the site; `/sitemaps/companies-sitemap.xml`
(80 shards, ~133k companies) and `/sitemaps/job-family-sitemap.xml` (20 shards,
~99k routes) enumerate it. `robots.txt` names `Claude-User` and allows it — a
user-initiated fetch is the case that file explicitly permits, so identify as
that rather than spoofing a desktop browser UA.

What each surface gives:
- `/companies/<slug>/salaries/software-engineer.md` — national median TC, the
  submission count behind it, and the per-level ladder. ~6KB. This is the
  reliable per-company measurement.
- `/t/software-engineer/locations/<metro>.md` — top **5** companies for that
  metro. Level- and focus-scoped variants repeat the metro's table, so they add
  nothing; only the bare `locations/` route is worth fetching.
- `/2025/report.md` — year-end report, top 5–7 per level/metro.

**What is gated, and why not to work around it.** The full ranking
(`/leaderboard/...` and the "sort companies by compensation" control) needs a
free account. The page renders the real top 3 and then five rows of *fabricated
filler* — "Tech Company", "Data Corp" — so a naive scrape silently yields junk.
The signup copy says the account exists to verify you are "not a bot or AI
scraper", so driving Devin's account through bulk extraction is the one path
that could get *his* account banned. Recompute the ranking from public
per-company pages instead.

**The WAF line, and a second quieter one.** Four concurrent workers with no
delay tripped AWS WAF's "Human Verification" challenge after ~400 requests; it
answers HTTP 405 with a `gokuProps` challenge body on every path, including
`robots.txt` and the sitemaps. It cleared on its own in ~3 minutes.

The second limit has no challenge page and is easy to misread as a hung script:
after roughly 2,300 requests in a session, levels.fyi simply stops answering —
connections hang until the 30s read timeout, over and over, so throughput
collapses to about one page an hour. Nothing says "blocked". Watch cache-file
mtimes rather than the progress counter to spot it. Budget ~2,000 requests per
session and expect to finish across two sittings; the disk cache makes a resume
free. `tools/levels_fyi_pay.py` has `--offline` to build the ranking from cache
alone, which is the right move once the site goes quiet.

Two bugs worth not repeating, both mine: retry transient `ReadTimeout` (an
unhandled one killed a 60-minute sweep before it wrote any output), and cap the
slug-variant search — 15 guesses × 2.5s each on companies that simply have no
US data was most of that hour.

Also worth knowing: `api.levels.fyi` has a real OpenAPI spec at
`/openapi.json` with a `top-companies` endpoint, but every route needs an
employer-issued `x-api-key` (401 without). And sitemap shards are served
uncompressed — the job-family set alone is ~650MB, so pull only what you need.

Attribution: Levels.fyi asks derived work to cite them.
See [[dont-declare-boards-unscrapable]] and [[job-search-targeting-criteria]].
