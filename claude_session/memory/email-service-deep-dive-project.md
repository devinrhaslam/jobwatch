---
name: email-service-deep-dive-project
description: "Devin's reusable interview deep-dive story — Happy Returns email service moved from sync HTTP to SNS→SQS after a P0 dropped ~10k emails; used for Datadog and Plaid."
metadata:
  node_type: memory
  type: project
  originSessionId: 018e4980-6889-43c2-ac84-50a22aaabb94
  modified: 2026-10-13T21:56:36.000Z
---

The project Devin uses for experience / deep-dive rounds. At Happy Returns, apps called an email service over synchronous HTTP, which called Postmark. Bursty enterprise-merchant volume made Postmark answer slowly (latency, not 429s); in-flight requests and in-process retries piled up in pod memory until pods OOMed, and a P0 dropped ~10,000 transactional emails. They were recovered only after hours of scripting against application logs. Devin owned the fix: a pod-memory stopgap, an RFC, SNS→SQS with fixed consumer concurrency, a DLQ after 3 failures with a redrive script and runbook, a Statsig per-producer rollout (1% → 5% → …), tickets and manager buy-in for producer services other teams owned, and a junior engineer on monitors and concurrency config. An architect pushed back (bigger pods + backoff/jitter; move to SES); the compromise split SES into a later track, which is in progress.

Never confirmed by Devin as of 2026-09-14: the service's language/runtime, pod count × concurrency, the exact visibility timeout (only "above Postmark's 60s timeout"), whether in-process retries survived into the consumer, Standard vs FIFO queue, whether consumers autoscale, project dates, and whether producers retried failed calls (he first described them as fire-and-forget with no retry; on 2026-09-28 he said he can't remember). Until confirmed, describe the loss mechanism neutrally: nothing recorded that the emails were owed, and nothing brought them back.

Question that stumped Devin in an interview (reported 2026-09-28, a company other than Plaid or Datadog): why touch the producers at all, rather than keep their HTTP calls and have the email service enqueue to SQS internally and return 202? Prepared answer: that fixes the OOM with no cross-team work, but the first hop stays non-durable for fire-and-forget callers, so an email-service outage or bad deploy still silently drops email; SNS moves where durability begins to the producer's own publish call. The honest concession is sequencing: ship the internal enqueue first, migrate producers second. Still unknown: whether the legacy HTTP path kept calling Postmark synchronously during the migration. Follow-up "just make producers retry instead": that is still a change to every producer, so it doesn't avoid the coordination; the coordination was the cost of fixing fire-and-forget, not of choosing SNS. Retrying over HTTP is the weaker producer change: the email waits in producer memory, a long email-service outage exhausts retries, and recovery brings a retry spike; publishing to SNS is itself the non-fire-and-forget change, acknowledged by a durable queue.

An interviewer also pressed on how the ~10,000 dropped emails were identified (raised 2026-09-28). Open question: was the count 'owed minus what Postmark's outbound log shows as sent' (defensible) or 'received minus our own logged successes' (an upper bound — a pod that died waiting on Postmark never logged success even if Postmark sent it, so the resend likely duplicated some)? Devin doesn't remember yet. The ambiguity is the same one as the queue design's gap between sending and deleting a message; the fix is a stable ID on every email so 'did this go out?' is one lookup.

Study sheet (Datadog framing): https://claude.ai/code/artifact/d1fe3a03-363f-49ed-b33d-a103122ec5a8

**Why:** the same story is being reused across companies, so prep shouldn't be re-derived from scratch each time.
**How to apply:** start from the study sheet and the Plaid deck; never present the unconfirmed facts above as true — ask Devin. Related: [[plaid-technical-deep-dive]], [[datadog-system-design-prep]].

Decks (as of 2026-10-13), all in ~/Downloads: "Technical Deep Dive - Devin Haslam v2.pptx" is Devin's own 10-slide cut (title, how email worked ×2, problem ×2, incident, solution ×3, questions); he called these "the most solid slides" and used them in a recent interview, so build from it, not from the 16-slide Plaid deck. "Zipline Panel Presentation - Devin Haslam v2.pptx" (the un-suffixed file beside it is the superseded first pass) is the mixed-audience version built on it for [[zipline-onsite-2026-10]]: adds About me, a Happy Returns return-lifecycle slide, What it cost, The options, Driving it, Outcome, Lessons learned, plus two backup slides carried over from the Plaid deck. The "Fire-and-forget · no retry" label was replaced there with neutral wording; the 10-slide cut still has it.

Facts from Devin, 2026-10-13: the whole project took about 5–6 weeks ("if I remember right"). The return portal sends the QR-code and return-started emails, Returnista (the drop-off app) sends the drop-off email, and the retailer dashboard sends billing emails. His resume says "async SQS/Lambda design" for this project while the decks draw consumer pods; he has not said which is right.

Templates (Devin's recollection, 2026-10-09, stated as "I think", so unconfirmed): Happy Returns email templates were hardcoded in a shared library that the email service imported, i.e. changing a template meant a code change and deploy.
