package server

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"time"

	"github.com/jackc/pgx/v5"
)

const (
	loginTokenTTL = 15 * time.Minute
	sessionTTL    = 30 * 24 * time.Hour
)

// ErrInvalidToken covers a login token that is unknown, expired, or already used.
var ErrInvalidToken = errors.New("invalid or expired token")

// newToken returns a fresh random token and its storage hash. The raw value goes
// in the email (login) or to the client (session); only the hash is persisted.
func newToken() (raw, hash string) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic("crypto/rand failed: " + err.Error())
	}
	raw = base64.RawURLEncoding.EncodeToString(b)
	return raw, hashToken(raw)
}

func hashToken(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(sum[:])
}

// CreateLoginToken stores a login token's hash against a user with an expiry.
func (s *Store) CreateLoginToken(ctx context.Context, userID, hash string, expires time.Time) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO login_tokens (token_hash, user_id, expires_at) VALUES ($1, $2, $3)`,
		hash, userID, expires)
	return err
}

// ConsumeLoginToken atomically spends a login token: it marks the row used and
// returns the user only if the token was unused and unexpired. A second attempt
// with the same token finds no eligible row and returns ErrInvalidToken.
func (s *Store) ConsumeLoginToken(ctx context.Context, hash string) (string, error) {
	var userID string
	err := s.pool.QueryRow(ctx, `
		UPDATE login_tokens SET used_at = now()
		WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()
		RETURNING user_id`, hash,
	).Scan(&userID)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", ErrInvalidToken
	}
	return userID, err
}

// CreateSession stores a session token's hash against a user with an expiry.
func (s *Store) CreateSession(ctx context.Context, userID, hash string, expires time.Time) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO sessions (token_hash, user_id, expires_at) VALUES ($1, $2, $3)`,
		hash, userID, expires)
	return err
}

// UserBySession resolves a live session token hash to its user, or ErrNotFound
// if it is unknown or expired.
func (s *Store) UserBySession(ctx context.Context, hash string) (string, error) {
	var userID string
	err := s.pool.QueryRow(ctx,
		`SELECT user_id FROM sessions WHERE token_hash = $1 AND expires_at > now()`, hash,
	).Scan(&userID)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", ErrNotFound
	}
	return userID, err
}

// DeleteSession revokes a session (logout). Deleting an unknown token is a no-op.
func (s *Store) DeleteSession(ctx context.Context, hash string) error {
	_, err := s.pool.Exec(ctx, `DELETE FROM sessions WHERE token_hash = $1`, hash)
	return err
}
