---
name: system-design-interview-weak-spot
description: "System design is Devin's recurring interview soft spot — Capital One, Datadog, and a Sept 2026 prepfully mock. The stall is the transition into high-level design; the observed symptom is over-depth in the step just before it."
metadata: 
  node_type: memory
  type: user
  originSessionId: 2f295328-d76d-4c62-b033-133c89635ef0
  modified: 2026-09-21T00:00:00.000Z
---

Devin interviewed at Datadog for a role with an **AI system design** round
(confirmed 2026-08-24): 60 min in Excalidraw, split ~10 min framing / ~10 min
high-level design / ~25 min deep dives, senior candidates expected to drive the
deep dives. The recruiter's example problem was a **flight recommender**. The
published rubric weights **distributed systems 45 points vs AI-specific 30**.
Datadog rejected him 2026-09-02 after the final rounds ("a very close call") —
the weak spot below is still the likely reason, and still the thing to fix for
the next loop. Details kept as a worked example. See [[datadog-code-review-round]].

**The stall is the transition into high-level design.** Requirements and NFR
gathering go fine, then the blank diagram is where it falls apart.

This is a **recurring** pattern across three data points:

1. **Capital One Power Day (Aug 2026)** — aced case, behavioral, and coding;
   only "okay" on system design; offered Lead rather than Senior Lead. See
   [[capital-one-offer-2026-08]].
2. **Datadog (Aug–Sep 2026)** — rejected after finals, "very close call."
3. **Prepfully mock (Sep 2026)** — feedback was "going too deep too early,"
   specifically getting bogged down in **sync vs async during the API step**.
   The interviewer prescribed switching to the system-design-primer's
   four-step approach.

**Working hypothesis (Sep 2026):** the over-depth and the stall are the same
bug, not two. The API step is list-shaped and linear, so it feels safe; the
blank diagram doesn't. Lingering in APIs *defers* the diagram, then he arrives
at it with less time and more pressure, which makes the stall worse. So the fix
is reps on the diagram, not a new framework — the framework isn't the problem.

**How to apply:** skip requirements-gathering basics — he has that. The API step
should be signatures only (~3 min), with depth questions parked out loud
("interesting — let me come back to that on the write path") rather than
answered in place. Drill the **first 15 minutes only**, repeatedly, with one
pass/fail check: are the boxes on the board? The request-path traversal method
in [[datadog-system-design-prep]] already targets this — it needs reps, not a
rewrite. Points live in the DS half of the rubric. His background is Go/AWS
event-driven backend plus a real CV/ML history, so lean on examples in that
shape. Related: [[job-search-targeting-criteria]].
