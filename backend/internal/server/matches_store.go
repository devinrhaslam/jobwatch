package server

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
)

// ErrNoProfile is returned when a user exists but has not set a profile, which
// matching requires.
var ErrNoProfile = errors.New("no profile")

// Profile returns the user's fit-filter profile text, or ErrNotFound if the user
// does not exist / ErrNoProfile if they exist but have not set one.
func (s *Store) Profile(ctx context.Context, userID string) (string, error) {
	var text string
	err := s.pool.QueryRow(ctx,
		`SELECT profile_text FROM user_profiles WHERE user_id = $1`, userID,
	).Scan(&text)
	if errors.Is(err, pgx.ErrNoRows) {
		ok, existsErr := s.userExists(ctx, userID)
		if existsErr != nil {
			return "", existsErr
		}
		if !ok {
			return "", ErrNotFound
		}
		return "", ErrNoProfile
	}
	return text, err
}

// LastMatchedAt returns the user's matching cursor, or nil if never matched.
func (s *Store) LastMatchedAt(ctx context.Context, userID string) (*time.Time, error) {
	var ts *time.Time
	err := s.pool.QueryRow(ctx,
		`SELECT last_matched_at FROM users WHERE id = $1`, userID,
	).Scan(&ts)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	return ts, err
}

// CandidateJobs returns the jobs to evaluate for a user this run: those in the
// watchlist first seen after both the user's cursor and the moment they added
// that company. The per-company added_at floor is the seeding boundary — a
// company added today can only ever surface jobs first seen after today.
func (s *Store) CandidateJobs(ctx context.Context, userID string, since *time.Time) ([]Job, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT j.company, j.job_id, j.title, j.url, j.location, j.posted_date,
		       j.first_seen_at, j.last_seen_at
		FROM jobs j
		JOIN user_companies uc ON uc.company = j.company
		WHERE uc.user_id = $1
		  AND j.first_seen_at > GREATEST(uc.added_at, COALESCE($2, 'epoch'::timestamptz))
		ORDER BY j.first_seen_at, j.job_id`, userID, since)
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

// FitVerdicts returns the cached verdicts for the given jobs under one profile
// hash, keyed by (company, title, location).
func (s *Store) FitVerdicts(ctx context.Context, hash string, jobs []Job) (map[verdictKey]Verdict, error) {
	out := map[verdictKey]Verdict{}
	if len(jobs) == 0 {
		return out, nil
	}
	companies := make([]string, len(jobs))
	titles := make([]string, len(jobs))
	locations := make([]string, len(jobs))
	for i, j := range jobs {
		k := keyFor(j)
		companies[i], titles[i], locations[i] = k.company, k.title, k.location
	}

	rows, err := s.pool.Query(ctx, `
		SELECT fv.company, fv.title, fv.location, fv.keep, fv.reason
		FROM fit_verdicts fv
		JOIN unnest($2::text[], $3::text[], $4::text[]) AS c(company, title, location)
		  ON fv.company = c.company AND fv.title = c.title AND fv.location = c.location
		WHERE fv.profile_hash = $1`, hash, companies, titles, locations)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var k verdictKey
		var v Verdict
		if err := rows.Scan(&k.company, &k.title, &k.location, &v.Keep, &v.Reason); err != nil {
			return nil, err
		}
		out[k] = v
	}
	return out, rows.Err()
}

// SaveFitVerdicts caches a batch of verdicts. jobs and verdicts are aligned by
// index. ON CONFLICT DO NOTHING makes a concurrent writer harmless.
func (s *Store) SaveFitVerdicts(ctx context.Context, hash string, jobs []Job, verdicts []Verdict) error {
	batch := &pgx.Batch{}
	for i, j := range jobs {
		k := keyFor(j)
		batch.Queue(`
			INSERT INTO fit_verdicts (profile_hash, company, title, location, keep, reason)
			VALUES ($1, $2, $3, $4, $5, $6)
			ON CONFLICT (profile_hash, company, title, location) DO NOTHING`,
			hash, k.company, k.title, k.location, verdicts[i].Keep, verdicts[i].Reason)
	}
	return s.pool.SendBatch(ctx, batch).Close()
}

// StageMatch records a keeper for a user, idempotently.
func (s *Store) StageMatch(ctx context.Context, userID string, job Job, reason string) error {
	_, err := s.pool.Exec(ctx, `
		INSERT INTO matches (user_id, company, job_id, reason)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (user_id, company, job_id) DO NOTHING`,
		userID, job.Company, job.JobID, reason)
	return err
}

// SetLastMatchedAt advances the user's matching cursor to now.
func (s *Store) SetLastMatchedAt(ctx context.Context, userID string) error {
	_, err := s.pool.Exec(ctx, `UPDATE users SET last_matched_at = now() WHERE id = $1`, userID)
	return err
}

// Match is a staged keeper joined to its job for display.
type Match struct {
	Company     string    `json:"company"`
	JobID       string    `json:"job_id"`
	Title       string    `json:"title"`
	URL         string    `json:"url"`
	Location    *string   `json:"location"`
	Reason      string    `json:"reason"`
	MatchedAt   time.Time `json:"matched_at"`
	FirstSeenAt time.Time `json:"first_seen_at"`
}

// Matches lists a user's staged keepers, newest match first.
func (s *Store) Matches(ctx context.Context, userID string, since time.Time, limit int) ([]Match, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT m.company, m.job_id, j.title, j.url, j.location, m.reason,
		       m.matched_at, j.first_seen_at
		FROM matches m
		JOIN jobs j ON j.company = m.company AND j.job_id = m.job_id
		WHERE m.user_id = $1 AND m.matched_at > $2
		ORDER BY m.matched_at DESC, m.job_id
		LIMIT $3`, userID, since, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	matches := []Match{}
	for rows.Next() {
		var m Match
		if err := rows.Scan(
			&m.Company, &m.JobID, &m.Title, &m.URL, &m.Location,
			&m.Reason, &m.MatchedAt, &m.FirstSeenAt,
		); err != nil {
			return nil, err
		}
		matches = append(matches, m)
	}
	return matches, rows.Err()
}
