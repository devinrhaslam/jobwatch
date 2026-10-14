---
name: jobwatch-anthropic-credits-recurring-interruption
description: "The Anthropic API key jobwatch uses for its role filter has now run out of credit six times (2026-08-10, 08-19, 08-26, 08-30, 09-01, 09-22)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 17edf1f9-e391-46bc-beee-65bb7dcd3839
  modified: 2026-09-01T19:37:22.168Z
---

The Claude API key `jobwatch`'s role filter (`classify_with_claude` in
`jobwatch/filters.py`) calls has hit "Your credit balance is too low to
access the Anthropic API" five separate times: 2026-08-10, 08-19, 08-26,
08-30, 09-01, and 09-22. 08-30 and 09-01 were consecutive daily runs — the balance
was not topped up between them. Each run fails open and dumps every unfiltered
new job to `output/<date>.json` (~1700–1825 jobs, ~600KB, vs ~60–80KB for a
clean run — the file size alone tells you it fail-opened).

Recovery so far: [[jobwatch-local-run-environment]] (`tools/refilter_report.py`)
and [[jobwatch-crash-before-report-recovery]] — but both need the API working.
On 09-01 the API was *still* down, so the only way to filter the run was by
hand: applying the `INSTRUCTIONS` + `CANDIDATE_PROFILE` prompt from
`jobwatch/filters.py` directly (rule-based drop of the obvious ~85%, then
judging the ~250 borderline SWE titles). Result lands in
`output/<date>-filtered.{txt,json}` like the tool's, but it's Claude-in-session
judgment, not the Opus classifier — don't write it into
`state/filter_cache.json`; let the real classifier redo it when credits return.

On 09-22 credits had been topped up by the time Devin asked, so
`tools/refilter_report.py` worked directly (1558 unfiltered → 68 kept).
Try the tool first before hand-filtering.

**Why:** this is now a hard pattern, not a one-off — five times in three weeks,
and the recovery tooling doesn't help when the outage persists past the run.

**How to apply:** next time this comes up, push Devin to fix the source —
auto-reload in the Anthropic Console Plans & Billing, or a dedicated key with a
budget alert — rather than recovering again. If a run already fail-opened and
the API is still down, hand-filter per the process above.
