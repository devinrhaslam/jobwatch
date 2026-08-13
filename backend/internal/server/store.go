package server

import (
	"context"
	"time"

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
