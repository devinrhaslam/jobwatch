---
name: jobwatch-crash-before-report-recovery
description: "New tools/recover_interrupted_run.py recovers a run.py invocation that died mid-scrape, before any output/ file was written"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 17edf1f9-e391-46bc-beee-65bb7dcd3839
  modified: 2026-08-26T12:02:03.507Z
---

`run.py` only calls `write_report()` once, at the very end, after every
company is scraped AND the role filter runs — so a run killed mid-scrape
(machine slept, terminal killed, anything short of a clean exit) leaves
**no** `output/<date>.json` at all, distinct from the already-documented
fail-open case in [[jobwatch-local-run-environment]] where the report *is*
written but unfiltered. This first showed up 2026-08-25/26: a local run
processed 184 of 267 companies (20:12:56–20:22:35 EDT) then died after
"Visa" — note `sorted(SCRAPERS)` is a case-sensitive sort, so "eBay",
"monday.com", "xAI" sort after every uppercase-initial name and land at the
very end, not interleaved alphabetically.

Nothing scraped was actually lost: `JsonSnapshotStore.save()` writes each
company's `state/<company>.json` immediately after that company finishes,
and `merge_snapshot()` stamps a job's `first_seen` the instant it's first
recorded and never touches that field again (in UTC — a local-evening run
can land on the next UTC date, so match by absolute timestamp/epoch, not a
date-string prefix). So any record whose `first_seen` falls inside the dead
run's time window *is* the new-job diff that run found.

`tools/recover_interrupted_run.py` (added 2026-08-26) auto-detects that
window from `state/*.json` mtimes (the trailing cluster with no gap over
`GAP_THRESHOLD_SECONDS`), rebuilds `CompanyResult`s from it, treats a
company as a same-night seed (reports nothing, matching `engine.py`) if
*every* record in its snapshot falls in the window, runs the same role
filter, fails open the same way `run.py` does if the classifier is down, and
writes `output/<label>-recovered.json`/`.txt` — feed the `.json` to
`tools/refilter_report.py` later if it had to fail open.

**How to apply:** if a scheduled or local run's `output/` file for a given
day is missing, don't assume the jobs are gone — run
`source ~/.zshrc && .venv/bin/python3 tools/recover_interrupted_run.py`
before re-scraping anything.

**Gotcha (2026-09-29):** the tool's "Not reached" list is really "no job
first_seen in the window", so since the pipeline went to every-two-hours
(commit 48533c6) it lumps scraped-but-quiet companies in with genuinely
unreached ones (reported 106 "not reached" when only 4 were). To find the
truly unreached companies, compare `state/*.json` mtimes against the window.
Files stale by weeks are scrapers that error every run (failures don't save);
that's a separate problem.
