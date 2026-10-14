---
name: jobwatch-seed-runs-are-the-fragile-path
description: "In jobwatch, the seed run is where silent data corruption happens, not the daily run"
metadata: 
  node_type: memory
  type: project
  originSessionId: aaf39b51-2230-4361-8dd1-41cefbccbffc
  modified: 2026-08-05T00:30:01.850Z
---

jobwatch's daily runs are cheap and self-correcting; its **seed runs** are
where things go wrong quietly. Seeding a board means hundreds of paginated
requests, and a seed that stops partway records part of a board as the whole
of it — so everything the run never reached is reported as new next time.
Microsoft hit this on 2026-08-04, storing 436 of 1,849 postings and reporting
"seeded" as if complete.

**Why:** the engine already refused to persist a *zero-job* seed for exactly
this reason. A truncated seed is the same failure, just quiet enough to look
like success. It now fails loudly and re-seeds next run.

**How to apply:** when adding a scraper, the seed is the case to test, not the
diff — run it to completion and check the count against the site's own
displayed total before believing it. Watch for boards that rate-limit: Microsoft
limits on *new connections* rather than request rate, which is why
`jobwatch/fetch.py` keeps one shared `requests.Session` — slowing the request
rate did not help and connection reuse did. Related:
[[dont-declare-boards-unscrapable]] and
[[jobwatch-dead-links-are-the-recurring-bug]].
