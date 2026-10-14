---
name: stubhub-technical-rounds
description: StubHub Senior SWE Supply Core technical rounds (Oct 8-9 2026) — format and the publicly reported recurring questions
metadata:
  node_type: memory
  type: project
  originSessionId: dd315196-4abb-4737-854b-5aa5677575e5
  modified: 2026-10-07T12:27:33.116Z
---

StubHub, Senior Software Engineer - Supply Core (Fullstack). Recruiter Joseph Gordon, coordinator Ida Badri.

- Code pair: 2026-10-08 2:30-4:00pm EDT (75 min + buffer), Chongshu Qian + Ali Rehman. Languages allowed: C#, Go, Java, JavaScript, Python3. Recruiter email: one problem in parts, OOP, data objects, date-time library, "no brute force".
- System design: 2026-10-09 2:30-3:30pm EDT, Tianxu Zhang + Richard Fornario, on Excalidraw.

Public reports (Blind, LeetCode discuss 5223346, prachub, linkjob; 2024-2026) are unusually consistent:
- Code pair = "marketing engine": Customer/Event classes, `send_customer_notifications`; parts: same-city events → event closest to next birthday → 5 nearest by distance → 5 cheapest via a slow/flaky price API → make campaigns composable (Strategy). 5-6 parts; finishing all parts matters.
- System design = marketing/event email notification system ("1M emails in 5 minutes", or 1M events emailing registrants). One variant: internal chat + 10-day-inactivity re-engagement emails. Not "design Ticketmaster".

The prep PDF attachment (`StubHub_Interview_Prep_-_SIM_-_BE_(1).pdf`) could not be read by the Gmail connector (no attachment download; browsers not signed in) as of 2026-10-07.

Related: [[system-design-interview-weak-spot]], [[email-service-deep-dive-project]] (the SNS→SQS story maps directly onto the email-system prompt).

2026-10-07: on the prep call, recruiter Joseph Gordon told Devin the coding problem is "related to email notification" — consistent with the marketing-engine question. Devin did a full Python mock of Q1-Q5 the same day; recurring slips were not running code before submitting, the `bisect_left` off-by-one (before is `index - 1`), and skipping clarifying questions.

2026-10-08 outcome: Devin reports the code pair went great. The real problem was a refreshed variant, not the leaked one: same domain objects (events, customers, campaigns) but it opened with vague product requirements he had to scope himself, and the work was ranking events with a weighted scoring algorithm (his idea) rather than filtering. Lesson: leaked StubHub questions give the theme, not the text; prep the family of problems. Fresh search the same day found 2026 system design reports in the same shape — interviewer pastes ~4 vague product requirements, unclear which systems already exist (Glassdoor, Feb 2026); topics seen: marketing email platform (scheduling, time zones, A/B testing, attribution), recommendation system (May 2026), A/B experimentation.

2026-10-09 outcome: Devin reports the system design round went well (recruiter had confirmed it would be an email problem; he prepped a campaign email platform design in chunks: send workers + email DB + DLQ, tracking service + stream, nightly preparer + send cron). Next step he expects: a final round of ~3 behavioral interviews; no confirmation email in the inbox as of this date. Public reports describe the post-technical stage as 2 behavioral rounds (Director of Engineering: unstructured project deep dive with interruptions, "why not X", business impact, "propose a new idea"; hiring manager: project deep dive, coworker disagreement). One Blind candidate was rejected after it for "not enough experience".
