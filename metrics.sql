-- Launch gates.
--
-- These are the five numbers the MVP exists to produce, written down before
-- launch so the thresholds cannot be rationalised afterwards. Run them against
-- production with:
--
--     psql "$JOBWATCH_DATABASE_URL" -f metrics.sql
--
-- A note on what is deliberately NOT here: an "opens" gate. Apple Mail Privacy
-- Protection pre-fetches images, so an unknowable share of digest_opened rows
-- are a proxy server rather than a person. Opens are recorded and are useful
-- directionally, but every threshold below is anchored on clicks, which require
-- a human.

\echo '== GATE 1: reach — 100 signups in the first 14 days =='
SELECT count(*) FILTER (WHERE name = 'signup_started')   AS signups_started,
       count(*) FILTER (WHERE name = 'signup_confirmed') AS signups_confirmed
FROM events
WHERE created_at > now() - interval '14 days';

\echo ''
\echo '== GATE 2: activation — target >=60% of signups confirm =='
-- Confirmation is the double opt-in click. A low number here means the email
-- never arrived (deliverability) or the value was not clear enough to bother.
WITH f AS (
    SELECT count(*) FILTER (WHERE name = 'signup_started')   AS started,
           count(*) FILTER (WHERE name = 'signup_confirmed') AS confirmed
    FROM events
)
SELECT started, confirmed,
       round(100.0 * confirmed / nullif(started, 0), 1) AS pct_confirmed
FROM f;

\echo ''
\echo '== GATE 3: value — target >=35% of subscribers click a role in 7 days =='
-- The only gate that tests the actual thesis. A subscriber who opens and never
-- clicks is telling you the matching is wrong, and no amount of distribution
-- fixes that.
WITH cohort AS (
    SELECT id, confirmed_at
    FROM users
    WHERE confirmed_at IS NOT NULL
      AND confirmed_at < now() - interval '7 days'
), clicked AS (
    SELECT DISTINCT e.user_id
    FROM events e
    JOIN cohort c ON c.id = e.user_id
    WHERE e.name = 'job_clicked'
      AND e.created_at <= c.confirmed_at + interval '7 days'
)
SELECT (SELECT count(*) FROM cohort)  AS eligible_subscribers,
       (SELECT count(*) FROM clicked) AS clicked_at_least_one,
       round(100.0 * (SELECT count(*) FROM clicked)
                   / nullif((SELECT count(*) FROM cohort), 0), 1) AS pct_clicked;

\echo ''
\echo '== GATE 4: retention — target >=30% still clicking in week 4 =='
-- The hard one, and the one that decides whether this is a business or a
-- novelty. Success causes churn here (they get the job and leave), so read a
-- soft number against that backdrop rather than against a SaaS benchmark.
WITH cohort AS (
    SELECT id, confirmed_at
    FROM users
    WHERE confirmed_at IS NOT NULL
      AND confirmed_at < now() - interval '28 days'
), active_w4 AS (
    SELECT DISTINCT e.user_id
    FROM events e
    JOIN cohort c ON c.id = e.user_id
    WHERE e.name IN ('job_clicked', 'prefs_changed')
      AND e.created_at BETWEEN c.confirmed_at + interval '21 days'
                           AND c.confirmed_at + interval '28 days'
)
SELECT (SELECT count(*) FROM cohort)    AS cohort_size,
       (SELECT count(*) FROM active_w4) AS active_week_4,
       round(100.0 * (SELECT count(*) FROM active_w4)
                   / nullif((SELECT count(*) FROM cohort), 0), 1) AS pct_retained;

\echo ''
\echo '== GATE 5: money — 10 paying, or >=5% of subscribers, whichever is higher =='
\echo '   (no billing yet — this gate is stubbed until there is something to buy)'

\echo ''
\echo '== Health: unsubscribe rate, the number that kills a sending domain =='
-- Above roughly 0.5% per send is a warning; complaints (which you see in the
-- Resend dashboard, not here) matter even more.
SELECT count(*) FILTER (WHERE name = 'digest_sent')  AS digests_sent,
       count(*) FILTER (WHERE name = 'unsubscribed') AS unsubscribes,
       round(100.0 * count(*) FILTER (WHERE name = 'unsubscribed')
                   / nullif(count(*) FILTER (WHERE name = 'digest_sent'), 0), 2) AS pct
FROM events
WHERE created_at > now() - interval '30 days';

\echo ''
\echo '== Which roles actually get clicked, by level =='
-- Feeds the next product decision: if clicks cluster in one level band, that is
-- the segment to aim the next launch post at.
SELECT e2.level, count(*) AS clicks
FROM events ev
JOIN job_enrichment e2
  ON e2.company = ev.props->>'company'
 AND e2.job_id  = ev.props->>'job_id'
WHERE ev.name = 'job_clicked'
  AND ev.created_at > now() - interval '30 days'
GROUP BY e2.level
ORDER BY clicks DESC;

\echo ''
\echo '== Supply: what the pipeline is actually producing per day =='
-- Watch this through September. The entry-level thesis depends on the
-- intern/new_grad line climbing as the season opens; if it does not, the
-- segment has a supply problem no amount of marketing solves.
SELECT date_trunc('day', j.first_seen_at)::date AS day,
       count(*)                                          AS new_ids,
       count(*) FILTER (WHERE e.is_swe)                   AS software,
       count(*) FILTER (WHERE e.is_swe AND e.is_us)       AS software_us,
       count(*) FILTER (WHERE e.is_swe
                          AND e.level IN ('intern', 'new_grad')) AS early_career
FROM jobs j
LEFT JOIN job_enrichment e ON e.company = j.company AND e.job_id = j.job_id
WHERE NOT j.is_seed
  AND j.first_seen_at > now() - interval '30 days'
GROUP BY 1
ORDER BY 1 DESC;
