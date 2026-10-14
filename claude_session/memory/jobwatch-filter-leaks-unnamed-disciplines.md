---
name: jobwatch-filter-leaks-unnamed-disciplines
description: "jobwatch's role filter leaks any engineering discipline its prompt doesn't name — fix the rule, not the instance"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 459c0e0f-dfad-4df7-a1af-faf2e05955c6
  modified: 2026-08-06T01:49:36.146Z
---

The role-fit prompt in `jobwatch/filters.py` pairs a **denylist** of excluded
tracks with a "when genuinely borderline, prefer relevant=true" tiebreaker.
Any discipline the list does not name lands in that tiebreaker and gets kept —
the model reliably *notices* the mismatch and keeps the job anyway, so the
cached reason reads like a confession ("mobile but engineering", "Staff
frontend SWE, US").

**Why:** on 2026-08-05 an Android role leaked; the fix named mobile
specifically. A frontend role leaked the very next run through the identical
gap. Patching the instance bought one day.

**How to apply:** when a wrong job gets through, check whether the prompt
excludes that *specific* thing or states a *rule*. Prefer the rule — the
prompt now says a title naming any engineering discipline is decisive and that
the borderline tiebreaker covers level, location and scope but never
discipline. Before adding another name to the denylist, ask whether the
general rule already covers it. Editing the prompt changes
`prompt_fingerprint()` and discards the verdict cache, which is intended and
cheap: only *new* jobs are ever classified, so the cache only saves on repeat
titles. See [[jobwatch-dead-links-are-the-recurring-bug]] and
[[job-search-targeting-criteria]].
