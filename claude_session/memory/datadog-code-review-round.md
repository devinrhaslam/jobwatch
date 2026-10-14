---
name: datadog-code-review-round
description: "Devin's Datadog loop also has a 60-min AI-enabled code review round; language choice committed to Go."
metadata: 
  node_type: memory
  type: project
  originSessionId: a4a5cbad-a4af-45fa-9b72-dba9f0c52585
  modified: 2026-09-09T20:31:35.487Z
---

**Outcome (2026-09-09): this loop is closed.** Devin did the final rounds
2026-09-01 and Datadog rejected 2026-09-02 (recruiter Margaret O'Reilly, "a
very close call" at the debrief). Datadog is now on his jobwatch skip list. Keep
this and [[datadog-system-design-prep]] as reusable prep material for the *next*
company with an AI code-review / AI system-design round — the format recurs —
not as live Datadog prep.

Devin's Datadog loop includes a **60-minute AI-enabled code review round**
(confirmed 2026-08-24), separate from the system design round in
[[system-design-interview-weak-spot]]. Format: ~10 min intro, ~40 min reviewing a
PR, ~10 min their questions. Candidate picks Python, Go, or Rust; findings go in
a file; no implementation. Platform is either CoderPad (AI Assist: ChatGPT /
Claude / Gemini / Llama) or Datadog's "Remote Code" VS Code environment (Claude
Code + Codex) — coordination team confirms which.

Scored on: driving the exercise, *verifying* AI findings against the code,
prioritization, scaling and failure-mode discussion, and finishing with an
explicit recommendation. The stated anti-patterns are process failures — bare
"review this diff" prompts, unverified AI output, and running out of time.

**Decision made:** he's going with **Go** — his working language, Datadog's
backend language, and its planted-bug classes (goroutine leaks, dropped `ctx`,
shadowed `err`, slice aliasing) are legible in a diff.

**How to apply:** prep artifact with the 40-minute run sheet, finding taxonomy,
and prompt library lives at
https://claude.ai/code/artifact/7e662642-276b-4761-87dc-6afa0be05aca — update
that rather than rewriting the advice. The open next step is timed mock reviews
against Go PRs with planted bugs.
