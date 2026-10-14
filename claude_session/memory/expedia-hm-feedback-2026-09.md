---
name: expedia-hm-feedback-2026-09
description: Written feedback from Expedia's hiring manager after the SDE III screen (Sept 2026) — the two gaps named were producer-side capacity/priority design and production AI depth.
metadata:
  type: project
---

Expedia (SDE III, AdTech) passed on Devin after the 2026-09-23 hiring manager screen with Sandeep Tharayil, and the recruiter sent itemized feedback on 2026-09-28. It is the most specific written feedback of the whole search.

Praised: the email-service incident story (downstream latency, in-flight request pile-up, move to async), at-least-once delivery with message IDs and time-bound dedup, AI use with clear ownership, clarifying questions and restating the problem.

Gaps named:
- Designing for constrained downstream capacity while preserving priority: they wanted an independent approach to producer-side rate limiting, capacity allocation, and keeping low-priority work from starving.
- Production AI depth: prompt-based integration was seen as a foundation only; they wanted model evaluation, validation, reliability, latency, cost, and operating models in production.
- Go/Python rather than Java was noted, and called not the main factor.

**Why:** Both gaps recur in design rounds and line up with [[system-design-interview-weak-spot]]; the incident story it praised is [[email-service-deep-dive-project]].

**How to apply:** When prepping Devin for a design or hiring-manager round, rehearse rate limiting at the producer, priority queues with starvation protection, and a concrete answer on evaluating and operating a model in production.
