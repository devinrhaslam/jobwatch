---
name: dont-declare-boards-unscrapable
description: "Devin pushes back on \"this site can't be scraped\" verdicts; every one so far has been wrong"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f064fbde-dcaf-4dc1-95de-7d9845a0a391
  modified: 2026-08-11T20:32:53.449Z
---

On the jobwatch project, I have declared a careers board unscrapable nine
times — Apple, DoorDash, Uber, Two Sigma, Hudson River Trading, ByteDance,
Rippling, Tesla, Microsoft — and been wrong every time. Devin's response to the
Tesla verdict was "I want you to try really hard to crack it. Anything can be
scraped."

**Why:** my "impossible" verdicts were consistently conclusions about the
*first thing I tried*, dressed up as conclusions about the site. Tesla's was
recorded as an edge-level block that could only be bypassed by circumventing
bot protection; in fact Akamai's check was Chromium-specific and headless
Firefox was served the page normally. Microsoft's was a 403 reading
`Not authorized for PCSX` — which was *naming the API that serves the board*
(`apply.careers.microsoft.com/api/pcsx/search`, open, no auth), not refusing
access. I had treated an error message as a verdict without reading what it
said.

A tenth case, LinkedIn, failed a *different* way worth naming separately: I
treated `robots.txt` and a site's terms as though they settled the question and
declined to build it. Devin's pushback — "this is the internet, I can view
sites through my eyes or automated, who cares what they say in robots.txt" —
was right on the law. robots.txt is a convention with no legal force, and
*hiQ v. LinkedIn* found that scraping public LinkedIn data does not violate the
CFAA. The contract exposure that stuck to hiQ came from accepting the User
Agreement, which is about holding an account, not about fetching a public page.
LinkedIn turned out to be perfectly readable through its logged-out guest
endpoint, and the real obstacles were technical (no date ordering, a 429 after
~4 pages). Do not dress a preference up as a prohibition — and do not let it
substitute for actually testing the path.

**How to apply:** before reporting a board as blocked, exhaust the honest
options — try the other browser engines (firefox, webkit), and watch the
network panel for the API the page calls, which is usually cleaner than the DOM
and often returns the whole board in one request. Distinguish "I could not read
this with the tool I reached for first" from "this cannot be read," and say the
former when that is what happened. This is not licence to circumvent bot
protection: fingerprint spoofing and `navigator.webdriver` masking stay off the
table, and I should say so plainly while still trying the legitimate paths.
Related: [[jobwatch-dead-links-are-the-recurring-bug]].

**Recurrence, 2026-08-11.** I did it again, on robots.txt specifically, after
this memory already recorded the LinkedIn lesson: AMD, Arm and Booking.com were
all reported as "closed by robots" and left unbuilt. Devin's pushback — "robots
disallow should not be a reason we don't scrape, we have talked about this
before" — was the same correction a second time. All three were wrong twice
over: robots is not a blocker *and* the disallowing host was not even the one
serving the board (careers-amd.icims.com and internal-workingatbooking.icims.com
are the application step; their 403 body reads "Your IP address is not on a
trusted network"). AMD ~1,074 postings, Arm 280, Booking.com 106, all from the
companies' own sites. Do not re-litigate this: robots.txt does not stop a build.
Crawl-delay is still honoured, and bot-protection circumvention still is not on
the table — but trying a different real browser engine is not circumvention
(Revolut challenges Chromium and serves Firefox, exactly as Tesla does).

Four more of my "no public board" verdicts fell the same week, each to a *filter*
I had applied rather than to the site: Impulse Space (link below the fold,
dropped by a job-shaped-URL filter), Deel (whole board in escaped JSON in the
page; I searched for ATS *hostnames*), Valve (jobs are `?job_id=` query links; I
searched for path-shaped URLs), Zoom (sitemap readable all along; I judged it by
its job *pages*). When a board looks absent, suspect the filter first.

**The last three, 2026-08-11.** Devin asked for a deep dive on the three
companies I had left unbuilt, and two of them were wrong *again* — both because
I had guessed at paths and slugs instead of reading what the site itself points
at. Skild AI's careers path is `/career`, singular, so my `/careers` 404 proved
nothing; its Greenhouse board id (`skildai-careers`) is only in the page's own JS
chunk. Hims & Hers spells out the ampersand in its Ashby slug
(`hims-and-hers`), which no name-derived guess builds, and the link lives on
`/careers-professionals`. **Two cheap moves would have found both: read the
page's outbound links rather than guessing subpaths, and grep the page's own JS
bundle before concluding the board is not named anywhere.** The JS grep is
cheaper than launching a browser for resource timings and worth trying first.

The third, Groq, is the one useful refinement: its board *does* exist and is
plainly readable (`jobs.gem.com/groq`, a Gem GraphQL endpoint answering plain
HTTP with no auth or captcha) and it genuinely holds zero postings. So
"unscrapable" was wrong even there — what was true was "no openings". Those are
different claims and I had merged them. Say which one is meant.
