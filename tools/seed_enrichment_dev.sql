-- Dev-only: fill job_enrichment with crude, title-derived guesses so the web app
-- and the digest can be exercised locally without an ANTHROPIC_API_KEY.
--
-- These are NOT the production verdicts. The real enricher (cmd/digest, see
-- backend/internal/server/enrich.go) reads the same title with a model and is
-- considerably better — in particular it recognises company-specific ladders and
-- knows when to answer `unknown`, which the regexes below mostly cannot.
--
-- Safe to re-run. Never run this against production: it would mask genuinely
-- unenriched rows from the nightly pass, since a row with a matching title_hash
-- is considered already judged.
--
--     docker exec -i applications-postgres-1 \
--         psql -U jobwatch -d jobwatch < tools/seed_enrichment_dev.sql

INSERT INTO job_enrichment
    (company, job_id, title_hash, is_swe, level, is_us, is_remote, reason, judged_at)
SELECT
    j.company,
    j.job_id,
    -- Must match titleHash() in enrich.go exactly, or the real enricher will
    -- consider every one of these rows stale and re-judge the lot.
    left(encode(sha256(convert_to(
        'claude-haiku-4-5-20251001' || E'\n' || j.title || E'\n' || coalesce(j.location, ''),
        'UTF8')), 'hex'), 16),

    j.title ~* '(software|sde\b|swe\b|developer|back[- ]?end|front[- ]?end|full[- ]?stack|platform engineer|infrastructure engineer|site reliability|\bsre\b|devops|security engineer|embedded|firmware|machine learning engineer|data engineer|mobile engineer|ios engineer|android engineer)'
      AND j.title !~* '(manager|director|recruit|sales|marketing|counsel|analyst|scientist|designer|mechanical|electrical|hardware|technician|accountant|nurse)',

    CASE
        WHEN j.title ~* '(intern\b|internship|co-?op\b|campus (under)?grad)' THEN 'intern'
        WHEN j.title ~* '(new ?grad|university grad|early career|rotational)'  THEN 'new_grad'
        WHEN j.title ~* '(junior|\bjr\.?\b|associate|entry[- ]level|engineer i\b|engineer 1\b)' THEN 'junior'
        WHEN j.title ~* '(engineer (ii|iii|2|3)\b|mid[- ]level)'               THEN 'mid'
        WHEN j.title ~* '(senior|\bsr\.?\b|\bsnr\b)'                          THEN 'senior'
        WHEN j.title ~* '(staff|principal|distinguished|fellow|architect)'      THEN 'staff'
        ELSE 'unknown'
    END,

    -- Absent or unrecognised locations count as US, matching the prompt's rule
    -- that missing evidence must never hide a role.
    NOT (coalesce(j.location, '') ~* '(india|bengaluru|bangalore|london|dublin|tokyo|singapore|toronto|berlin|paris|amsterdam|sydney|tel aviv|remote - (emea|india|apac|canada|uk))'),

    coalesce(j.location, '') ~* '(remote|distributed|work from home)',
    'dev seed',
    now()
FROM jobs j
WHERE NOT j.is_seed
ON CONFLICT (company, job_id) DO NOTHING;
