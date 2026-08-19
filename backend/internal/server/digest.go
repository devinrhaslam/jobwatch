package server

import (
	"context"
	"errors"
	"log"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
)

// digestMaxJobs bounds one email. At roughly 300 new software roles a day across
// the tracked companies, an unfiltered digest is already long; this is the point
// past which more listings stop being useful and the email starts being a wall.
// The overflow is counted and linked, never silently dropped.
const digestMaxJobs = 60

// defaultDigestInterval is the minimum gap between one subscriber's digests.
//
// 23 hours rather than 24 because ingestion runs every two hours. At exactly 24
// the eligible moment lands a hair after the run that last sent, so the send
// slips to the next slot and walks two hours later every day until it is
// arriving at 4am. Shaving an hour keeps the same daily slot eligible run after
// run, and lets a missed run recover at the next slot instead of shifting
// everyone's delivery time permanently.
const defaultDigestInterval = 23 * time.Hour

// DigestSummary reports what a digest run did.
type DigestSummary struct {
	Subscribers int `json:"subscribers"`
	EmailsSent  int `json:"emails_sent"`
	JobsSent    int `json:"jobs_sent"`
	Skipped     int `json:"skipped_no_jobs"`
}

// RunDigests is one pass of the alerting loop, meant to be invoked on a schedule
// (see cmd/digest): for every confirmed subscriber it selects the postings first
// seen since their cursor that match their filters, emails them, and advances the
// cursor — so a posting is emailed exactly once.
//
// A failure for one subscriber is logged and skipped rather than aborting the
// run: one bad address must not stop everyone else's digest.
func (s *Server) RunDigests(ctx context.Context) (DigestSummary, error) {
	subs, err := s.store.Subscribers(ctx, s.digestInterval)
	if err != nil {
		return DigestSummary{}, err
	}

	var sum DigestSummary
	for _, sub := range subs {
		sum.Subscribers++

		since, err := s.digestCursor(ctx, sub.ID)
		if err != nil {
			log.Printf("digest: cursor for %s failed: %v", sub.Email, err)
			continue
		}

		jobs, err := s.store.NewPostingsFor(ctx, sub, since, digestMaxJobs)
		if err != nil {
			log.Printf("digest: selecting for %s failed: %v", sub.Email, err)
			continue
		}
		if len(jobs) == 0 {
			// No email at all rather than an empty one. An alert product that
			// mails "nothing today" teaches people to stop opening it.
			sum.Skipped++
			continue
		}

		// Counted rather than inferred from an over-fetch, so "and N more" is
		// the real remainder. A full page of results is the common case, not
		// the edge one.
		overflow := 0
		if len(jobs) == digestMaxJobs {
			total, err := s.store.CountNewPostingsFor(ctx, sub, since)
			if err != nil {
				log.Printf("digest: counting for %s failed: %v", sub.Email, err)
			} else if total > len(jobs) {
				overflow = total - len(jobs)
			}
		}

		if err := s.mailer.SendDigest(ctx, sub, s.buildDigest(sub, jobs, overflow)); err != nil {
			log.Printf("digest: sending to %s failed: %v", sub.Email, err)
			continue
		}
		// Only advance after a send that succeeded, so a provider outage means a
		// delayed digest rather than postings nobody is ever told about.
		if err := s.store.SetLastDigestAt(ctx, sub.ID); err != nil {
			log.Printf("digest: advancing cursor for %s failed: %v", sub.Email, err)
			continue
		}
		s.store.RecordEvent(ctx, EventDigestSent, &sub.ID, map[string]any{
			"jobs":     len(jobs),
			"overflow": overflow,
		})
		sum.EmailsSent++
		sum.JobsSent += len(jobs)
	}
	return sum, nil
}

// digestCursor is where this subscriber's next digest starts: their last digest,
// or — for someone who has never been sent one — the moment they confirmed.
//
// Anchoring a first digest to confirmation rather than to the epoch is what stops
// a new subscriber's first email being the entire back catalogue.
func (s *Server) digestCursor(ctx context.Context, userID string) (time.Time, error) {
	var last, confirmed *time.Time
	err := s.store.pool.QueryRow(ctx,
		`SELECT last_digest_at, confirmed_at FROM users WHERE id = $1`, userID,
	).Scan(&last, &confirmed)
	if errors.Is(err, pgx.ErrNoRows) {
		return time.Time{}, ErrNotFound
	}
	if err != nil {
		return time.Time{}, err
	}
	if last != nil {
		return *last, nil
	}
	if confirmed != nil {
		return *confirmed, nil
	}
	return time.Now(), nil
}

// DigestJob is one row of the email: the posting plus everything the template
// needs pre-resolved, so the mailer does no lookups and no per-user link
// building of its own.
type DigestJob struct {
	Job
	LogoURL string
	// URL to follow — the click-tracking redirect when tracking is on, the bare
	// posting URL when it is off.
	LinkURL string
	Age     string
}

// DigestContent is a rendered digest, ready for any mailer.
type DigestCompany struct {
	Company string
	LogoURL string
	Jobs    []DigestJob
}

type DigestContent struct {
	Total       int
	Overflow    int
	Companies   []DigestCompany
	AppURL      string
	PrefsURL    string
	UnsubURL    string
	PixelURL    string
	PostalAddr  string
	CompanyList []string // the first few company names, for the subject line
}

// buildDigest groups a subscriber's postings by company and resolves every link.
//
// Grouping is not decoration: a single run routinely yields nine near-identical
// Microsoft reqs, and ungrouped that reads as a wall of repeated text. Companies
// are ordered by their newest posting so the freshest employer leads.
func (s *Server) buildDigest(sub Subscriber, jobs []Job, overflow int) DigestContent {
	now := time.Now()
	order := []string{}
	byCompany := map[string][]DigestJob{}
	for _, j := range jobs {
		if _, seen := byCompany[j.Company]; !seen {
			order = append(order, j.Company)
		}
		byCompany[j.Company] = append(byCompany[j.Company], DigestJob{
			Job:     j,
			LogoURL: LogoURL(j.Company),
			LinkURL: s.TrackedJobURL(j.URL, j.Company, j.JobID, sub.ID),
			Age:     humanAge(now.Sub(j.FirstSeenAt)),
		})
	}

	content := DigestContent{
		Total:      len(jobs),
		Overflow:   overflow,
		AppURL:     s.appBaseURL,
		PrefsURL:   s.appBaseURL,
		UnsubURL:   s.UnsubscribeURL(sub.ID),
		PixelURL:   s.OpenPixelURL(sub.ID),
		PostalAddr: s.postalAddress,
	}
	for _, c := range order {
		content.Companies = append(content.Companies, DigestCompany{
			Company: c,
			LogoURL: LogoURL(c),
			Jobs:    byCompany[c],
		})
		if len(content.CompanyList) < 3 {
			content.CompanyList = append(content.CompanyList, c)
		}
	}
	return content
}

// humanAge renders how long ago a posting was first seen. Freshness is the whole
// product claim, and "3 hours ago" carries it in a way a calendar date does not.
func humanAge(d time.Duration) string {
	switch {
	case d < time.Minute:
		return "just now"
	case d < time.Hour:
		n := int(d.Minutes())
		return plural(n, "minute") + " ago"
	case d < 24*time.Hour:
		n := int(d.Hours())
		return plural(n, "hour") + " ago"
	default:
		n := int(d.Hours() / 24)
		return plural(n, "day") + " ago"
	}
}

func plural(n int, unit string) string {
	s := strconv.Itoa(n) + " " + unit
	if n != 1 {
		s += "s"
	}
	return s
}

// LastDigestAt returns when the subscriber was last emailed, or nil if never.
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

// SetLastDigestAt advances the subscriber's digest cursor to now.
func (s *Store) SetLastDigestAt(ctx context.Context, userID string) error {
	_, err := s.pool.Exec(ctx, `UPDATE users SET last_digest_at = now() WHERE id = $1`, userID)
	return err
}
