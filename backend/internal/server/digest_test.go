package server

import (
	"context"
	"testing"
)

// captureMailer records the digests it is asked to send instead of mailing them.
type capturedDigest struct {
	email   string
	matches []Match
}

type captureMailer struct {
	digests []capturedDigest
}

func (m *captureMailer) SendLoginLink(_ context.Context, _, _ string) error { return nil }

func (m *captureMailer) SendDigest(_ context.Context, email string, matches []Match) error {
	m.digests = append(m.digests, capturedDigest{email: email, matches: matches})
	return nil
}

func TestDigestEmailsNewMatchesExactlyOnce(t *testing.T) {
	srv := setup(t)
	stub := &stubClassifier{off: []string{"Frontend"}}
	userID, _ := matchReadyUser(t, srv, stub, "digest@example.com")
	backdateWatchlist(t, userID, "2025-01-01T00:00:00Z")

	mail := &captureMailer{}
	srv.mailer = mail

	sum, err := srv.RunDigests(context.Background())
	if err != nil {
		t.Fatalf("run digests: %v", err)
	}
	if sum.Users != 1 || sum.EmailsSent != 1 || sum.MatchesSent != 1 {
		t.Fatalf("summary = %+v, want 1 user / 1 email / 1 match", sum)
	}
	if len(mail.digests) != 1 || mail.digests[0].email != "digest@example.com" {
		t.Fatalf("captured = %+v", mail.digests)
	}
	if got := mail.digests[0].matches; len(got) != 1 || got[0].JobID != "1" {
		t.Fatalf("digest matches = %+v, want only the backend role", got)
	}

	// A second run finds nothing new: the cursor advanced past the sent matches.
	sum2, err := srv.RunDigests(context.Background())
	if err != nil {
		t.Fatalf("run digests again: %v", err)
	}
	if sum2.EmailsSent != 0 {
		t.Fatalf("second run sent %d emails, want 0", sum2.EmailsSent)
	}
	if len(mail.digests) != 1 {
		t.Fatalf("second run captured another digest: %+v", mail.digests)
	}
}

func TestDigestSkipsUsersWithNoMatches(t *testing.T) {
	srv := setup(t)
	stub := &stubClassifier{}
	// No backdate: added_at is now, so the fixture's older jobs are below the
	// seeding floor and nothing matches.
	matchReadyUser(t, srv, stub, "empty@example.com")

	mail := &captureMailer{}
	srv.mailer = mail

	sum, err := srv.RunDigests(context.Background())
	if err != nil {
		t.Fatalf("run digests: %v", err)
	}
	if sum.Users != 1 || sum.EmailsSent != 0 {
		t.Fatalf("summary = %+v, want 1 user / 0 emails", sum)
	}
	if len(mail.digests) != 0 {
		t.Fatalf("emailed a user with no matches: %+v", mail.digests)
	}
}
