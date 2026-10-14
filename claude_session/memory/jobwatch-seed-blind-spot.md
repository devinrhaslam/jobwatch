---
name: jobwatch-seed-blind-spot
description: "Listings already up at a company's first scrape never reach the digest; companies that keep the same listings up for months are invisible to jobwatch."
metadata:
  node_type: memory
  type: project
  originSessionId: 928c075d-b45a-4fa8-b218-7ac3f86c07ee
  modified: 2026-09-27T17:23:57.356Z
---

jobwatch reports nothing on a seed run (engine.py `reported_new = [] if is_seed_run`),
so any listing live on day one is never shown. On 2026-09-27, 21,442 such listings
were still live; 852 unique roles passed the role filter.

Companies that post very few new listings (≤5% of their board per week; the median is 9%):
Character.AI, Valve, Confluent, Pinecone, Palantir (median listing ~15 months old), Cresta,
WorkOS, Neuralink, Rockstar, Skild, Figure, Cognition, Modal, Veeva, Scale AI,
Decagon, Cursor. Their long-lived listings are general roles they hire into
continuously; many have been up for more than a year.

Page: https://claude.ai/artifact/BSzwMrCPpSNy7wuT7axbbk. Built by scratchpad scripts
(not committed): survivors = live now AND first_seen within 12h of seed;
title/location prefilter; then `jobwatch.filters.classify()` (verdicts now in
filter_cache.json); joined with `tools/levels_fyi_pay.py --json` at 8 years of experience.

**Why:** Devin asked for this because the digest can never surface these roles.
**How to apply:** if asked to refresh it, rerun the same pipeline; it could also become a
one-off "backlog" report per newly seeded company. Relates to [[jobwatch-seed-runs-are-the-fragile-path]].
