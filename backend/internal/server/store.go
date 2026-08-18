package server

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Store is the read side of the jobwatch schema. It owns a connection pool and
// exposes exactly the queries the API needs — nothing writes here; ingestion is
// the Python worker's job.
type Store struct {
	pool *pgxpool.Pool
}

func newStore(ctx context.Context, dsn string) (*Store, error) {
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return nil, err
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	return &Store{pool: pool}, nil
}

// Close releases the pool. Safe to call once, at shutdown.
func (s *Store) Close() { s.pool.Close() }

// Job mirrors a row of the jobs table. Location and PostedDate are pointers
// because the source genuinely omits them for some boards, and a null must
// serialize as JSON null rather than an empty string that implies "known blank".
type Job struct {
	Company     string    `json:"company"`
	JobID       string    `json:"job_id"`
	Title       string    `json:"title"`
	URL         string    `json:"url"`
	Location    *string   `json:"location"`
	PostedDate  *string   `json:"posted_date"`
	FirstSeenAt time.Time `json:"first_seen_at"`
	LastSeenAt  time.Time `json:"last_seen_at"`
}

// scanJobs drains a query whose columns are the Job SELECT list below. Every job
// query shares it so the column order lives in one place.
func scanJobs(rows pgx.Rows) ([]Job, error) {
	jobs := []Job{}
	for rows.Next() {
		var j Job
		if err := rows.Scan(
			&j.Company, &j.JobID, &j.Title, &j.URL, &j.Location,
			&j.PostedDate, &j.FirstSeenAt, &j.LastSeenAt,
		); err != nil {
			return nil, err
		}
		jobs = append(jobs, j)
	}
	return jobs, rows.Err()
}

// Companies lists every company with at least one stored job, alphabetically.
func (s *Store) Companies(ctx context.Context) ([]string, error) {
	rows, err := s.pool.Query(ctx, `SELECT DISTINCT company FROM jobs ORDER BY company`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	companies := []string{}
	for rows.Next() {
		var c string
		if err := rows.Scan(&c); err != nil {
			return nil, err
		}
		companies = append(companies, c)
	}
	return companies, rows.Err()
}

// Jobs returns stored jobs first-seen strictly after `since`, newest first. An
// empty company means "any company"; the strict `>` is what makes `since` usable
// as a caller's cursor without re-serving the boundary row.
func (s *Store) Jobs(ctx context.Context, company string, since time.Time, limit int) ([]Job, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT company, job_id, title, url, location, posted_date,
		       first_seen_at, last_seen_at
		FROM jobs
		WHERE ($1 = '' OR company = $1)
		  AND first_seen_at > $2
		ORDER BY first_seen_at DESC, job_id
		LIMIT $3`, company, since, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	return scanJobs(rows)
}

// RecentPostings returns jobs first seen since `since` that are NOT part of a
// company's initial seed — only postings that appeared after the company was
// first tracked. A seed writes a company's whole board at one timestamp, which
// is that company's earliest first_seen; "first_seen later than that earliest"
// is exactly the genuinely-new set. Newest first.
func (s *Store) RecentPostings(ctx context.Context, since time.Time, limit int) ([]Job, error) {
	rows, err := s.pool.Query(ctx, `
		WITH seeds AS (
			SELECT company, min(first_seen_at) AS seeded_at FROM jobs GROUP BY company
		)
		SELECT j.company, j.job_id, j.title, j.url, j.location, j.posted_date,
		       j.first_seen_at, j.last_seen_at
		FROM jobs j
		JOIN seeds s ON s.company = j.company
		WHERE j.first_seen_at > $1
		  AND j.first_seen_at > s.seeded_at
		ORDER BY j.first_seen_at DESC, j.job_id
		LIMIT $2`, since, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	return scanJobs(rows)
}

// Health is the payload of /health: a DB liveness signal plus corpus size and
// the companies whose most recent run ended badly. Problems is empty until
// run.py records into company_runs (a later slice), but the query is wired now.
type Health struct {
	Status    string   `json:"status"`
	Jobs      int64    `json:"jobs"`
	Companies int64    `json:"companies"`
	Problems  []string `json:"problems"`
}

func (s *Store) Health(ctx context.Context) (Health, error) {
	h := Health{Status: "ok", Problems: []string{}}
	if err := s.pool.QueryRow(ctx,
		`SELECT count(*), count(DISTINCT company) FROM jobs`,
	).Scan(&h.Jobs, &h.Companies); err != nil {
		return h, err
	}

	// The latest run per company, surfacing any that did not end cleanly.
	rows, err := s.pool.Query(ctx, `
		SELECT DISTINCT ON (company) company, status
		FROM company_runs
		ORDER BY company, ran_at DESC`)
	if err != nil {
		return h, err
	}
	defer rows.Close()
	for rows.Next() {
		var company, status string
		if err := rows.Scan(&company, &status); err != nil {
			return h, err
		}
		switch status {
		case "failed", "blocked", "suspicious":
			h.Problems = append(h.Problems, company)
		}
	}
	return h, rows.Err()
}

// SoftwareFeed is the public home page's query: genuinely-new US software roles
// since `since`, capped at perCompany per company so a busy employer cannot
// flood the page, newest first.
//
// This used to fetch a wide window and classify in the request path. Enrichment
// now happens once in the cron, so the feed is pure SQL — no model call, no
// cache lookup, and the per-company cap is a window function rather than a
// second pass in Go.
func (s *Store) SoftwareFeed(ctx context.Context, since time.Time, perCompany, limit int) ([]Job, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT company, job_id, title, url, location, posted_date,
		       first_seen_at, last_seen_at
		FROM (
			SELECT j.company, j.job_id, j.title, j.url, j.location, j.posted_date,
			       j.first_seen_at, j.last_seen_at,
			       row_number() OVER (PARTITION BY j.company
			                          ORDER BY j.first_seen_at DESC, j.job_id) AS rn
			FROM jobs j
			JOIN job_enrichment e ON e.company = j.company AND e.job_id = j.job_id
			WHERE NOT j.is_seed
			  AND j.first_seen_at > $1
			  AND e.is_swe
			  AND e.is_us
		) ranked
		WHERE rn <= $2
		ORDER BY first_seen_at DESC, job_id
		LIMIT $3`, since, perCompany, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanJobs(rows)
}

// Stats is the public proof-of-life on the landing page: how much is tracked and
// how much arrived today. These are the numbers that make the pitch credible, so
// they are served from the same table the feed reads rather than hardcoded.
type Stats struct {
	Companies int64 `json:"companies"`
	Jobs      int64 `json:"jobs"`
	NewToday  int64 `json:"new_today"`
}

func (s *Store) Stats(ctx context.Context, since time.Time) (Stats, error) {
	var st Stats
	err := s.pool.QueryRow(ctx, `
		SELECT (SELECT count(DISTINCT company) FROM jobs),
		       (SELECT count(*) FROM jobs),
		       (SELECT count(*)
		          FROM jobs j
		          JOIN job_enrichment e ON e.company = j.company AND e.job_id = j.job_id
		         WHERE NOT j.is_seed AND j.first_seen_at > $1 AND e.is_swe AND e.is_us)`,
		since,
	).Scan(&st.Companies, &st.Jobs, &st.NewToday)
	return st, err
}
