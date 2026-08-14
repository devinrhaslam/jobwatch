package server

import (
	"context"
	"errors"
	"log"
	"time"

	"github.com/jackc/pgx/v5"
)

// DigestSummary reports what a digest run did.
type DigestSummary struct {
	Users       int `json:"users"`
	EmailsSent  int `json:"emails_sent"`
	MatchesSent int `json:"matches_sent"`
}

type digestUser struct {
	id    string
	email string
}

// RunDigests is one pass of the alerting loop, meant to be invoked on a schedule
// (see cmd/digest): for every user with a profile and a watchlist, it runs
// matching to stage any new keepers, then emails the matches staged since their
// last digest and advances the cursor — so each match is emailed exactly once.
// A failure for one user is logged and skipped rather than aborting the run.
func (s *Server) RunDigests(ctx context.Context) (DigestSummary, error) {
	users, err := s.store.usersForDigest(ctx)
	if err != nil {
		return DigestSummary{}, err
	}

	var sum DigestSummary
	for _, u := range users {
		sum.Users++

		if _, err := s.runMatch(ctx, u.id); err != nil {
			log.Printf("digest: matching for %s failed: %v", u.email, err)
			continue
		}

		since := time.Unix(0, 0).UTC()
		last, err := s.store.LastDigestAt(ctx, u.id)
		if err != nil {
			log.Printf("digest: cursor for %s failed: %v", u.email, err)
			continue
		}
		if last != nil {
			since = *last
		}

		matches, err := s.store.Matches(ctx, u.id, since, 1000)
		if err != nil {
			log.Printf("digest: matches for %s failed: %v", u.email, err)
			continue
		}
		if len(matches) == 0 {
			continue
		}

		if err := s.mailer.SendDigest(ctx, u.email, matches); err != nil {
			log.Printf("digest: sending to %s failed: %v", u.email, err)
			continue
		}
		if err := s.store.SetLastDigestAt(ctx, u.id); err != nil {
			log.Printf("digest: advancing cursor for %s failed: %v", u.email, err)
			continue
		}
		sum.EmailsSent++
		sum.MatchesSent += len(matches)
	}
	return sum, nil
}

// usersForDigest returns accounts eligible for a digest: those with a profile
// and at least one watched company.
func (s *Store) usersForDigest(ctx context.Context) ([]digestUser, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT u.id, u.email FROM users u
		WHERE EXISTS (SELECT 1 FROM user_profiles p WHERE p.user_id = u.id)
		  AND EXISTS (SELECT 1 FROM user_companies c WHERE c.user_id = u.id)
		ORDER BY u.created_at`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	users := []digestUser{}
	for rows.Next() {
		var u digestUser
		if err := rows.Scan(&u.id, &u.email); err != nil {
			return nil, err
		}
		users = append(users, u)
	}
	return users, rows.Err()
}

// LastDigestAt returns when the user was last emailed, or nil if never.
func (s *Store) LastDigestAt(ctx context.Context, userID string) (*time.Time, error) {
	var ts *time.Time
	err := s.pool.QueryRow(ctx,
		`SELECT last_digest_at FROM users WHERE id = $1`, userID,
	).Scan(&ts)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	return ts, err
}

// SetLastDigestAt advances the user's digest cursor to now.
func (s *Store) SetLastDigestAt(ctx context.Context, userID string) error {
	_, err := s.pool.Exec(ctx, `UPDATE users SET last_digest_at = now() WHERE id = $1`, userID)
	return err
}
