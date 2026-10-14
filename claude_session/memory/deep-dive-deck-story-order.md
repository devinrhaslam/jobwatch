---
name: deep-dive-deck-story-order
description: Build Devin's deep-dive slides in his spoken story order, with diagrams that grow slide by slide — not in the interview template's section order.
metadata:
  type: feedback
---
Devin tells the email-service deep dive in this order: company context and why the emails matter → how the architecture worked → the problem (bursty volume, backpressure as latency, OOMing pods) → the incident and the memory stopgap → the solution (SNS + SQS, bursts become queue depth) → the delivery work (architect pushback, other teams' SNS changes, rollout) → what he'd do differently (bound memory by bytes, not message count). On 2026-09-14 he rejected a deck that followed Plaid's template order (problem-and-goals slide first, architecture second, execution last): it gave away the ending and made the architecture arrive too late.

**Why:** the listener needs the architecture before the problem makes sense, and he normally draws the diagram live — producers, email service, Postmark, then the red box.
**How to apply:** keep every template section's content but sequence it as the story; show diagrams as duplicated build slides (Morph optional) rather than one finished picture; put the options/tradeoffs comparison between the stopgap and the solution; move deeper design choices to backup slides. Related: [[plaid-technical-deep-dive]], [[email-service-deep-dive-project]].
