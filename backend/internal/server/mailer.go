package server

import (
	"context"
	"log"
)

// Mailer sends the transactional email the app depends on. The interface keeps
// the delivery mechanism (a real provider later) out of the handlers; the dev
// implementation just logs, so the auth flow is exercisable without an inbox.
type Mailer interface {
	SendLoginLink(ctx context.Context, email, link string) error
	SendDigest(ctx context.Context, email string, matches []Match) error
}

// logMailer is the development mailer: it writes the message to the server log
// instead of sending mail. Never use it in production — the "email" is visible
// to anyone reading logs.
type logMailer struct{}

func (logMailer) SendLoginLink(_ context.Context, email, link string) error {
	log.Printf("[dev mailer] login link for %s: %s", email, link)
	return nil
}

func (logMailer) SendDigest(_ context.Context, email string, matches []Match) error {
	log.Printf("[dev mailer] digest to %s: %d new match(es)", email, len(matches))
	for _, m := range matches {
		log.Printf("[dev mailer]   • %s — %s (%s)", m.Title, m.Company, m.Reason)
	}
	return nil
}
