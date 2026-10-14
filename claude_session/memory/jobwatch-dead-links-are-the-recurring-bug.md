---
name: jobwatch-dead-links-are-the-recurring-bug
description: "The bug class Devin actually reports on jobwatch is job links that don't resolve"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f064fbde-dcaf-4dc1-95de-7d9845a0a391
  modified: 2026-08-05T17:03:45.420Z
---

Every user-reported bug on jobwatch so far has been a **dead or wrong job
link**, not a missing or miscategorised job: Stripe and Pinterest links landing
on the listings index instead of the posting, and Uber links 404ing after Uber
migrated to Oracle Recruiting Cloud while its old API kept reporting the jobs
as live.

**Why:** the whole point of the tool is applying on day one, so a link that
does not open the posting wastes the only thing it delivers. A job that is
merely mis-ranked is a nuisance; a dead link is a failure.

**How to apply:** when adding a scraper, verify the URL scheme against several
*real* sampled postings before declaring it done — not just one, and preferring
titles with awkward punctuation. Prefer a URL form that cannot break: for Tesla
the slug in `.../job/<slug>-<id>` turned out to be decorative (the router keys
on the trailing id), which was worth testing explicitly with a deliberately
wrong slug. Also worth building at some point: a link-health spot-check that
samples stored URLs and flags non-resolving ones, which would have caught the
Uber migration automatically. Related:
[[dont-declare-boards-unscrapable]].

**Not every dead link is a jobwatch bug.** Greenhouse serves the scrape and the
click from two different hosts: `boards-api.greenhouse.io` (the board JSON, what
the scraper reads) and `job-boards.greenhouse.io` (the human-facing posting, what
the report links to). On 2026-08-05 the API host answered normally while the
posting host returned `406 Not Acceptable` from nginx for *every* path — every
board, every job id, even `/` — from Devin's network and from a separate cloud
egress, and to headless Firefox as readily as to curl, regardless of user agent.
So a green run proves nothing about whether its links open. Before touching URL
construction, fetch a **known-good control** and a **deliberately invalid job
id** on the same host: if both return the same status, the host is refusing
everything and the URL is not the problem.
