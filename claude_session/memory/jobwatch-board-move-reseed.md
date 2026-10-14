---
name: jobwatch-board-move-reseed
description: "When a jobwatch company changes ATS or re-IDs its board, it sticks as \"suspicious\" forever until re-seeded; recover the outage window by title diff"
metadata:
  node_type: memory
  type: project
  originSessionId: db615a54-67b8-4f68-af9d-b62e192c08a4
  modified: 2026-09-23T22:40:32.389Z
---

A board that changes ATS (Greenhouse → Ashby/Workday) or reissues job IDs
trips the engine's suspicious check (≥80% new of ≥20 jobs), and a suspicious
run **never saves its snapshot**, so it stays flagged every run until someone
intervenes. HRT sat that way from ~2026-09-02 to 09-23 unnoticed. Boards with
<20 jobs (World Labs, 11) skip the check and instead report every job as new.

**Why:** on 2026-09-23 six companies needed this at once (ClickHouse, Marqeta
→ Ashby `marqeta-inc`, Postman → Workday wd108, World Labs → Ashby, plus
Writer and HRT re-IDing in place). The fix is: move `state/<company>.json`
aside, rerun that company so it seeds, then diff the new board's titles
against the old snapshot and run the unseen ones through
`apply_filters_by_group` — re-seeding alone silently drops jobs posted during
the outage.

**How to apply:** in a report, repeated FAILED (404 from an ATS API) or
SUSPICIOUS across days is a board move, not a flake — check the careers page's
network requests or a posting's apply link for the new ATS. Also watch for
HTML entities (`&amp;`, `&#8211;`) in titles from self-hosted/WordPress or
`<title>`-scraped boards. Related: [[jobwatch-seed-runs-are-the-fragile-path]],
[[dont-declare-boards-unscrapable]].
