package server

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// ErrNotFound is returned when a lookup targets a user that does not exist.
var ErrNotFound = errors.New("not found")

type User struct {
	ID        string    `json:"id"`
	Email     string    `json:"email"`
	CreatedAt time.Time `json:"created_at"`
}

// UserView is the composite "everything about this account" payload: identity,
// the fit-filter profile (null until set), and the watchlist.
type UserView struct {
	User
	Profile   *string  `json:"profile"`
	Watchlist []string `json:"watchlist"`
}

func normalizeEmail(email string) string {
	return strings.ToLower(strings.TrimSpace(email))
}

// UpsertUser creates the account for an email or returns the existing one, so
// signup is idempotent: the same address never spawns a second account.
func (s *Store) UpsertUser(ctx context.Context, email string) (User, error) {
	var u User
	err := s.pool.QueryRow(ctx, `
		INSERT INTO users (email) VALUES ($1)
		ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
		RETURNING id, email, created_at`,
		normalizeEmail(email),
	).Scan(&u.ID, &u.Email, &u.CreatedAt)
	return u, err
}

func (s *Store) userExists(ctx context.Context, id string) (bool, error) {
	var exists bool
	err := s.pool.QueryRow(ctx,
		`SELECT EXISTS (SELECT 1 FROM users WHERE id = $1)`, id,
	).Scan(&exists)
	return exists, err
}

// UserView returns the account with its profile and watchlist, or ErrNotFound.
func (s *Store) UserView(ctx context.Context, id string) (UserView, error) {
	var v UserView
	err := s.pool.QueryRow(ctx, `
		SELECT u.id, u.email, u.created_at, p.profile_text
		FROM users u
		LEFT JOIN user_profiles p ON p.user_id = u.id
		WHERE u.id = $1`, id,
	).Scan(&v.ID, &v.Email, &v.CreatedAt, &v.Profile)
	if errors.Is(err, pgx.ErrNoRows) {
		return v, ErrNotFound
	}
	if err != nil {
		return v, err
	}
	watchlist, err := s.Watchlist(ctx, id)
	if err != nil {
		return v, err
	}
	v.Watchlist = watchlist
	return v, nil
}

// SetProfile upserts the account's profile text, or ErrNotFound if it is gone.
func (s *Store) SetProfile(ctx context.Context, id, text string) error {
	ok, err := s.userExists(ctx, id)
	if err != nil {
		return err
	}
	if !ok {
		return ErrNotFound
	}
	_, err = s.pool.Exec(ctx, `
		INSERT INTO user_profiles (user_id, profile_text, updated_at)
		VALUES ($1, $2, now())
		ON CONFLICT (user_id)
		DO UPDATE SET profile_text = EXCLUDED.profile_text, updated_at = now()`,
		id, text)
	return err
}

// Watchlist returns the companies a user watches, alphabetically.
func (s *Store) Watchlist(ctx context.Context, id string) ([]string, error) {
	rows, err := s.pool.Query(ctx,
		`SELECT company FROM user_companies WHERE user_id = $1 ORDER BY company`, id)
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

// UnknownCompanies returns the subset of names that are not tracked — i.e. have
// no jobs stored. An empty result means every name is watchable.
func (s *Store) UnknownCompanies(ctx context.Context, companies []string) ([]string, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT c FROM unnest($1::text[]) AS c
		WHERE NOT EXISTS (SELECT 1 FROM jobs WHERE company = c)`, companies)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	unknown := []string{}
	for rows.Next() {
		var c string
		if err := rows.Scan(&c); err != nil {
			return nil, err
		}
		unknown = append(unknown, c)
	}
	return unknown, rows.Err()
}

// SetWatchlist replaces a user's watchlist with exactly `companies`, in one
// transaction. A company already present keeps its original added_at; only
// genuinely new ones get added_at = now(). That preserves the per-user seeding
// boundary — re-saving an unchanged selection never resets anyone's cursor, and
// a company added today can only ever alert on jobs first seen after today.
func (s *Store) SetWatchlist(ctx context.Context, id string, companies []string) error {
	ok, err := s.userExists(ctx, id)
	if err != nil {
		return err
	}
	if !ok {
		return ErrNotFound
	}

	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	// Drop the ones no longer wanted. An empty array deletes the whole list,
	// since every row is `<> ALL('{}')`.
	if _, err := tx.Exec(ctx,
		`DELETE FROM user_companies WHERE user_id = $1 AND company <> ALL($2::text[])`,
		id, companies); err != nil {
		return err
	}
	// Add the rest; DO NOTHING on conflict keeps the original added_at.
	if _, err := tx.Exec(ctx, `
		INSERT INTO user_companies (user_id, company)
		SELECT $1, c FROM unnest($2::text[]) AS c
		ON CONFLICT (user_id, company) DO NOTHING`,
		id, companies); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
