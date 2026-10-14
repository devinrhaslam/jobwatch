---
name: job-search-targeting-criteria
description: "How Devin picks target companies for companies.txt — top comp, household names, no quant firms."
metadata: 
  node_type: memory
  type: project
  originSessionId: cda1576a-9a51-4a0c-aae2-0e4a48701f4b
  modified: 2026-08-05T12:10:15.635Z
---

When adding companies to `companies.txt`, Devin is optimizing for top-tier
compensation *and* brand recognition, and has ruled out quant/HFT firms
(Citadel, Optiver, DRW, IMC, Jump, etc.) as a poor match for his resume —
he is a backend/distributed-systems engineer, not a low-latency/C++ one.
He also pushed back on suggestions he had never heard of.

**Why:** on 2026-08-05 a suggestion list led with quant firms and unfamiliar
AI startups; both were rejected. The names he kept were recognizable ones
(Discord, Instacart, Robinhood, Palantir, Anduril, Spotify) plus a small
number of unfamiliar ones justified by a specific resume fit.

**How to apply:** lead with recognizable companies; skip quant entirely; when
proposing a name he is unlikely to know, justify it against his actual
background — Go/AWS event-driven backend, e-commerce/returns/payments domain
(HappyReturns, PayPal-owned), and a real CV/ML history (object detection,
3D reconstruction) that makes autonomy and robotics companies a live option.
Build difficulty is not a filter — he said explicitly he does not care how
hard a board is to scrape. See [[dont-declare-boards-unscrapable]].

**The bar is a number, and it is not the median (2026-09-20).** Devin has 8
years of experience and sits between senior and staff; his walk-away is ~$330k
total comp (the Capital One decline). Ranking companies by their levels.fyi
*company-wide median* is the wrong statistic and he rejected a 119-name list
built that way — "most of these companies are very small. I don't want to go
through an entire interview process and then learn that the offer is less than
330k." A company median averages in new grads, so it both flatters small
companies with flat ladders and buries big ones with long ones: Stripe's median
is $270k but its L3, the level an 8-year engineer lands, is $472k.

**How to apply:** price every company at the level whose levels.fyi experience
band *starts* at or below 8 years — the highest such level, never the nearest
band (nearest promotes him into Cisco's Distinguished Engineer, 21-23 yrs, and
reads Roku's Senior as reachable when it wants 12-14). `tools/levels_fyi_pay.py
--at-yoe 8 --bar 330000` does this. Level names are useless across companies;
the experience band is the only portable index.

The finding that matters: of 222 measured companies *not* already in
`companies.txt`, only **3** clear $330k at 8 years. His existing list already
holds ~44 that do. The list is not the constraint — market scarcity is, and the
bigger lever is being levelled up a rung (the next rung is routinely +$100k)
rather than adding more employers. See [[levels-fyi-access-path]].
