---
name: datadog-system-design-prep
description: "Prep artifact for Datadog's AI system-design round — walkthrough of an automated incident-investigation agent (Bits Investigation), built around request-path traversal and the 45/30 rubric split."
metadata: 
  node_type: memory
  type: reference
  originSessionId: c9235f03-62f2-4e1f-af08-6385d45b58dc
  modified: 2026-09-09T20:31:39.560Z
---

**Outcome (2026-09-09): Datadog loop closed — rejected 2026-09-02 after the
final rounds.** This artifact stays useful as prep for the next AI-system-design
round elsewhere; it is no longer live Datadog prep. See
[[datadog-code-review-round]].

Study reference built 2026-09-01 for Devin's Datadog **AI system design** round:
**https://claude.ai/code/artifact/a5fefcc1-b70b-4e16-8862-a200738d4a27**
("Designing Bits Investigation").

Covers: framing (kept deliberately short — not where points are), a
**request-path traversal** method for building the high-level diagram (write
path: alert → correlation key → create-or-attach → enqueue → ack; then read
path: lease → context → loop → synthesize → fan-out delivery), the
distributed-systems spine (Kafka, dedup/correlation store, investigation state
machine, idempotency, admission control, backpressure), the LLM investigation
loop (hypothesis-first, causal-only retrieval, tree search with pruning,
evidence board outside the context window), alert-storm correlation, token-cost
control, deep-dive Q&A cards, and a cheat sheet.

Weighted to the rubric: **distributed systems 45 pts vs AI-specific 30** — the
artifact leads with DS and marks the AI loop as the smaller half. The traversal
section directly targets the known stall point (the jump from requirements into
the blank diagram). See [[system-design-interview-weak-spot]].

If revising: republish to the same URL by passing it as `url`. Product facts
are from Datadog's public Bits AI SRE blog posts (linked in the artifact
footer); the recruiter's stated example problem was a flight recommender, which
shares the same skeleton.
