package server

import (
	"context"
	"errors"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Preferences is everything a subscriber can narrow their digest by. The zero
// value — no levels, us_only, not remote-only — is the default every new account
// gets, and it means "send me every US software role". Filters only ever remove.
type Preferences struct {
	// Empty means every level. A non-empty list is an opt-in narrowing; note
	// that listings whose title carries no level ('unknown') are delivered
	// regardless, because hiding a role on absent evidence is the worse error.
	Levels     []string `json:"levels"`
	USOnly     bool     `json:"us_only"`
	RemoteOnly bool     `json:"remote_only"`
}

// Subscriber is a confirmed account plus its filters — what the digest run needs
// and nothing else.
type Subscriber struct {
	ID    string
	Email string
	Preferences
}

// Preferences returns an account's filters.
func (s *Store) Preferences(ctx context.Context, userID string) (Preferences, error) {
	var p Preferences
	err := s.pool.QueryRow(ctx,
		`SELECT levels, us_only, remote_only FROM users WHERE id = $1`, userID,
	).Scan(&p.Levels, &p.USOnly, &p.RemoteOnly)
	if errors.Is(err, pgx.ErrNoRows) {
		return p, ErrNotFound
	}
	return p, err
}

// SetPreferences replaces an account's filters.
func (s *Store) SetPreferences(ctx context.Context, userID string, p Preferences) error {
	tag, err := s.pool.Exec(ctx,
		`UPDATE users SET levels = $2, us_only = $3, remote_only = $4 WHERE id = $1`,
		userID, p.Levels, p.USOnly, p.RemoteOnly)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

// Confirm completes double opt-in. It is idempotent and never moves an existing
// timestamp, so the confirmation date stays the date they actually confirmed.
// Returns true only on the transition, so the caller records the event once.
func (s *Store) Confirm(ctx context.Context, userID string) (bool, error) {
	tag, err := s.pool.Exec(ctx,
		`UPDATE users SET confirmed_at = now() WHERE id = $1 AND confirmed_at IS NULL`, userID)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() > 0, nil
}

// digestFilterSQL narrows enriched postings to a subscriber's preferences.
//
// The level clause is the important one: `e.level = ANY($n)` OR `e.level =
// 'unknown'`. About a third of real software titles name no level, and those
// must reach everyone — a filter here removes roles the subscriber said they did
// not want, never roles we simply could not classify.
const digestFilterSQL = `
	AND e.is_swe
	AND (NOT $2::boolean OR e.is_us)
	AND (NOT $3::boolean OR e.is_remote)
	AND (cardinality($4::text[]) = 0 OR e.level = ANY($4::text[]) OR e.level = '` + LevelUnknown + `')`

// NewPostingsFor returns the postings a subscriber has not been sent yet:
// genuinely-new, enriched, matching their filters, first seen strictly after
// their digest cursor. Newest first.
func (s *Store) NewPostingsFor(ctx context.Context, sub Subscriber, since time.Time, limit int) ([]Job, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT j.company, j.job_id, j.title, j.url, j.location, j.posted_date,
		       j.first_seen_at, j.last_seen_at
		FROM jobs j
		JOIN job_enrichment e ON e.company = j.company AND e.job_id = j.job_id
		WHERE NOT j.is_seed
		  AND j.first_seen_at > $1`+digestFilterSQL+`
		ORDER BY j.first_seen_at DESC, j.job_id
		LIMIT $5`,
		since, sub.USOnly, sub.RemoteOnly, sub.Levels, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanJobs(rows)
}

// CountNewPostingsFor is NewPostingsFor's total, ignoring the display limit.
//
// It exists so the email's "and N more" is honest. Deriving the overflow from an
// over-fetch of limit+1 can only ever say "and 1 more", which for a subscriber
// with no level filter — several hundred roles a day — understates the remainder
// by two orders of magnitude.
func (s *Store) CountNewPostingsFor(ctx context.Context, sub Subscriber, since time.Time) (int, error) {
	var n int
	err := s.pool.QueryRow(ctx, `
		SELECT count(*)
		FROM jobs j
		JOIN job_enrichment e ON e.company = j.company AND e.job_id = j.job_id
		WHERE NOT j.is_seed
		  AND j.first_seen_at > $1`+digestFilterSQL,
		since, sub.USOnly, sub.RemoteOnly, sub.Levels,
	).Scan(&n)
	return n, err
}

// Subscribers lists accounts due a digest: confirmed, not unsubscribed, and not
// emailed within minInterval. Deliberately does not require a profile or a
// watchlist — the MVP sends every subscriber the same query narrowed only by
// Preferences.
//
// minInterval is what separates how often the pipeline *looks* from how often a
// person is *emailed*. Ingestion runs every couple of hours so the public feed
// and the corpus stay fresh; without this gate that cadence would put a dozen
// digests a day in every inbox, which is the fastest way to burn a sending
// domain and the subscriber list with it.
//
// A subscriber skipped by this gate keeps their cursor, so nothing is lost —
// the postings simply accumulate into the next digest they are due.
func (s *Store) Subscribers(ctx context.Context, minInterval time.Duration) ([]Subscriber, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, email, levels, us_only, remote_only
		FROM users
		WHERE confirmed_at IS NOT NULL
		  AND unsubscribed_at IS NULL
		  AND (last_digest_at IS NULL
		       OR last_digest_at <= now() - make_interval(secs => $1))
		ORDER BY created_at`, int(minInterval.Seconds()))
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	subs := []Subscriber{}
	for rows.Next() {
		var sub Subscriber
		if err := rows.Scan(&sub.ID, &sub.Email, &sub.Levels, &sub.USOnly, &sub.RemoteOnly); err != nil {
			return nil, err
		}
		subs = append(subs, sub)
	}
	return subs, rows.Err()
}

func (s *Server) handleSetPreferences(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Levels     []string `json:"levels"`
		USOnly     *bool    `json:"us_only"`
		RemoteOnly *bool    `json:"remote_only"`
	}
	if !decodeJSON(w, r, &body) {
		return
	}

	// Normalise and validate rather than storing whatever arrives: an unknown
	// level in the column would filter nothing and look like a working setting.
	levels := make([]string, 0, len(body.Levels))
	seen := map[string]bool{}
	for _, l := range body.Levels {
		l = strings.ToLower(strings.TrimSpace(l))
		if l == "" || seen[l] {
			continue
		}
		if !isValidLevel(l) {
			writeError(w, http.StatusBadRequest,
				"unknown level "+l+"; valid levels are "+strings.Join(ValidLevels, ", "))
			return
		}
		seen[l] = true
		levels = append(levels, l)
	}

	prefs := Preferences{Levels: levels, USOnly: true}
	if body.USOnly != nil {
		prefs.USOnly = *body.USOnly
	}
	if body.RemoteOnly != nil {
		prefs.RemoteOnly = *body.RemoteOnly
	}

	userID := currentUser(r)
	if err := s.store.SetPreferences(r.Context(), userID, prefs); err != nil {
		if errors.Is(err, ErrNotFound) {
			writeError(w, http.StatusNotFound, "no such user")
			return
		}
		log.Printf("set preferences: %v", err)
		writeError(w, http.StatusInternalServerError, "could not save preferences")
		return
	}
	// Editing preferences is also how someone opts back in after unsubscribing.
	if err := s.store.Resubscribe(r.Context(), userID); err != nil {
		log.Printf("resubscribe on prefs change: %v", err)
	}
	s.store.RecordEvent(r.Context(), EventPrefsChanged, &userID, map[string]any{
		"levels":      levels,
		"us_only":     prefs.USOnly,
		"remote_only": prefs.RemoteOnly,
	})
	w.WriteHeader(http.StatusNoContent)
}
