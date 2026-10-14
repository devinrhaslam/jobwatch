---
name: zipline-onsite-2026-10
description: "Zipline Senior SWE (ASW Launch Ops) virtual onsite on 2026-10-14 — 45-min panel presentation to a mixed audience, then stakeholder, architecture and culture rounds."
metadata:
  node_type: memory
  type: project
  originSessionId: 018e4980-6889-43c2-ac84-50a22aaabb94
  modified: 2026-10-13T22:22:07.609Z
---

Zipline, Senior Software Engineer, ASW Launch Ops. Recruiter Dora Leung; coordinator Christina Jang. Earlier rounds: recruiter intro 2026-09-23, hiring manager ("Tiff") 2026-09-30, pre-onsite technical 2026-10-05. Zipline wanted an in-person onsite in South San Francisco; Devin asked for video (Richmond-based, little PTO) and they agreed, with a possible in-person visit later.

Virtual onsite, Wed 2026-10-14, Google Meet, times ET: 1:30–2:15 Panel Presentation (Cameron Waldman, Lexi Galantino, Nicolas Villanueva, Jose Nino Rivera); 2:15–3:00 Stakeholder Partnerships (Cameron Waldman); 3:30–4:30 Architecture (Nick Murray-Ishihara, Jose Nino Rivera); 4:30–5:00 Culture Fit (Lexi Galantino).

Panel brief (Dora, 2026-10-05): 45 minutes including questions, to a mix of engineers and non-technical stakeholders; the most challenging and complex problem he was responsible for driving, with timeline, impact, outcome and lessons learned; architecture diagrams welcome; an optional career-arc intro slide, 5 minutes at most. From the 2026-10-13 prep call, per Devin: non-technical panelists want who it affected, the outcome, and how he collaborated with stakeholders.

Architecture round subject, as told to Devin and relayed 2026-10-13: an app that tracks maintenance data for drones and decides whether each is airworthy. (That it is the 3:30 Architecture round, not another slot, is my inference.) Prep given in chat that day: event log → evaluator → status → launch gate, framed as a correctness/audit problem, not a scale one; drill per [[system-design-interview-weak-spot]]. The JD stresses data modeling, auditability, state transitions and exception handling.

The deck is the email-service story: see [[email-service-deep-dive-project]] for the file and its structure; slide style follows [[slides-prefer-images-over-text]].
