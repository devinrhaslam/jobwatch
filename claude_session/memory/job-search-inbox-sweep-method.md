---
name: job-search-inbox-sweep-method
description: How to sweep Devin's Gmail for in-flight interviews without missing companies — never filter out recruiting-system senders, and always check starred mail.
metadata:
  type: feedback
---

When Devin asks for his list of in-flight companies ("update my matrix"), missing a company is the failure he cares most about. It has happened four times (SpaceX, Render, Expedia, Robinhood on 2026-10-01).

**Why:** The Robinhood miss came from a "human senders only" Gmail query that excluded `notifications@`, `no-reply@`, Ashby, Greenhouse and similar senders. Recruiter outreach and scheduling mail is sent through exactly those systems (e.g. `notifications@recruiting.robinhood.com`, `notifications@guide.klaviyo.com`, Calendly, GoodTime, candidate.fyi, HackerRank). Following only the first page of results also dropped mail.

**How to apply:** Run all of these and read every page:
1. Recruiting-system senders: ashbyhq, greenhouse, lever, myworkday, icims, smartrecruiters, gem, goodtime, modernloop, candidate.fyi, guide.co, calendly, brighthire, hackerrank, codesignal.
2. Subject keywords: invitation, interview, phone screen, next steps, availability, assessment, schedule, recruiter, "let's chat", connect.
3. `is:starred` — Devin stars the recruiter emails he cares about.
4. Sent mail, to see what he has already answered.
For oversized results, list sender/subject/date with jq from the saved file instead of skipping. Report the list without tiers; he wants one flat list. See [[job-search-targeting-criteria]].
