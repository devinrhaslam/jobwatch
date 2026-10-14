---
name: jobwatch-local-run-environment
description: Two gotchas for invoking jobwatch scripts locally from a fresh shell — venv python and ANTHROPIC_API_KEY sourcing
metadata: 
  node_type: memory
  type: project
  originSessionId: 27184209-5aed-4f9c-a9a9-59a11c303a3a
  modified: 2026-08-26T12:02:30.801Z
---

Running jobwatch tooling locally (`run.py`, `tools/refilter_report.py`, etc.)
from a fresh non-interactive shell hits two gotchas:

1. Bare `python3` on PATH lacks the `anthropic` package (and jobwatch itself) —
   use `.venv/bin/python3` from the repo root.
2. `ANTHROPIC_API_KEY` is exported in `~/.zshrc`, which non-interactive Bash
   tool calls don't source automatically — `source ~/.zshrc` first, or the
   Claude API calls fail (distinct from the key being genuinely unset/invalid).

**Why:** cost a wasted round-trip recovering a run on 2026-08-19: first hit
`ModuleNotFoundError: anthropic` from bare `python3`, then had to confirm the
key loads only after sourcing the profile.

**How to apply:** for any local jobwatch invocation, run
`source ~/.zshrc && .venv/bin/python3 <script>` from `/Users/HMF4BGW/go/src/github.com/applications`.

Related: when `run.py`'s role filter fails mid-run (e.g. Claude API credits
exhausted), it deliberately fails open — snapshots are already saved, so it
prints/writes every new job unfiltered rather than losing them (see the
comment in `run.py`'s filter except-block). `tools/refilter_report.py`
re-runs just the classification step against the dated report in `output/`,
writing `<date>-filtered.json`/`.txt` alongside the untouched original — no
re-scrape needed, and it uses the same `state/filter_cache.json` cache. This
has already been used once before (2026-08-10) and once again (2026-08-19,
~4h/457 jobs → 37 kept after a mid-run billing lapse). Related:
[[jobwatch-dead-links-are-the-recurring-bug]].

That covers a run that finished scraping but whose filter failed. A run
killed mid-scrape (machine slept, terminal died) never reaches
`write_report()` at all, so `output/` has nothing for that day even though
`state/` was updated as far as the run got -- see
[[jobwatch-crash-before-report-recovery]] for `tools/recover_interrupted_run.py`,
which covers that case (first seen 2026-08-25/26). That recovery also hit
the same Claude-credits failure the filter has now hit three times; see
[[jobwatch-anthropic-credits-recurring-interruption]].
