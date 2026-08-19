package server

import (
	"context"
	"net/http"
	"strconv"
	"strings"
	"testing"
	"time"
)

func epoch() time.Time { return time.Unix(0, 0).UTC() }

// captureMailer records the digests it is asked to send instead of mailing them.
type capturedDigest struct {
	email   string
	content DigestContent
}

type captureMailer struct {
	digests []capturedDigest
}

func (m *captureMailer) SendLoginLink(_ context.Context, _, _ string) error { return nil }

func (m *captureMailer) SendDigest(_ context.Context, sub Subscriber, c DigestContent) error {
	m.digests = append(m.digests, capturedDigest{email: sub.Email, content: c})
	return nil
}

// jobIDs flattens a digest back to the postings it carried.
func (c capturedDigest) jobIDs() []string {
	var ids []string
	for _, company := range c.content.Companies {
		for _, j := range company.Jobs {
			ids = append(ids, j.JobID)
		}
	}
	return ids
}

func TestDigestSendsNewPostingsExactlyOnce(t *testing.T) {
	srv := setup(t)
	enrichAll(t, srv)
	confirmSubscriber(t, srv, "digest@example.com")

	mail := &captureMailer{}
	srv.mailer = mail

	sum, err := srv.RunDigests(context.Background())
	if err != nil {
		t.Fatalf("run digests: %v", err)
	}
	if sum.Subscribers != 1 || sum.EmailsSent != 1 || sum.JobsSent != 1 {
		t.Fatalf("summary = %+v, want 1 subscriber / 1 email / 1 role", sum)
	}
	if len(mail.digests) != 1 || mail.digests[0].email != "digest@example.com" {
		t.Fatalf("captured = %+v", mail.digests)
	}
	// Only Acme "2" is a non-seed software posting; the seeds are back-catalogue.
	if ids := mail.digests[0].jobIDs(); len(ids) != 1 || ids[0] != "2" {
		t.Fatalf("digest carried %v, want only job 2", ids)
	}

	// A second run finds nothing new: the cursor advanced past what was sent.
	sum2, err := srv.RunDigests(context.Background())
	if err != nil {
		t.Fatalf("run digests again: %v", err)
	}
	if sum2.EmailsSent != 0 || len(mail.digests) != 1 {
		t.Fatalf("second run re-sent: summary %+v, captured %d", sum2, len(mail.digests))
	}
}

func TestDigestSkipsUnconfirmedAccounts(t *testing.T) {
	srv := setup(t)
	enrichAll(t, srv)
	// Signed in but never clicked a confirmation link.
	signIn(t, srv, "unconfirmed@example.com")

	mail := &captureMailer{}
	srv.mailer = mail

	sum, err := srv.RunDigests(context.Background())
	if err != nil {
		t.Fatalf("run digests: %v", err)
	}
	if sum.Subscribers != 0 || len(mail.digests) != 0 {
		t.Fatalf("emailed an unconfirmed address: summary %+v, captured %+v", sum, mail.digests)
	}
}

func TestDigestSkipsUnsubscribed(t *testing.T) {
	srv := setup(t)
	enrichAll(t, srv)
	userID, _ := confirmSubscriber(t, srv, "gone@example.com")
	if err := srv.store.Unsubscribe(context.Background(), userID); err != nil {
		t.Fatalf("unsubscribe: %v", err)
	}

	mail := &captureMailer{}
	srv.mailer = mail
	sum, err := srv.RunDigests(context.Background())
	if err != nil {
		t.Fatalf("run digests: %v", err)
	}
	if sum.Subscribers != 0 || len(mail.digests) != 0 {
		t.Fatalf("emailed an unsubscribed address: %+v", mail.digests)
	}
}

func TestDigestSendsNothingRatherThanAnEmptyEmail(t *testing.T) {
	srv := setup(t)
	enrichAll(t, srv)
	// Confirmed now, so the cursor starts after every fixture posting.
	signIn(t, srv, "quiet@example.com")
	if _, err := srv.store.pool.Exec(context.Background(),
		`UPDATE users SET confirmed_at = now() WHERE email = 'quiet@example.com'`); err != nil {
		t.Fatalf("confirm: %v", err)
	}

	mail := &captureMailer{}
	srv.mailer = mail
	sum, err := srv.RunDigests(context.Background())
	if err != nil {
		t.Fatalf("run digests: %v", err)
	}
	if sum.Subscribers != 1 || sum.EmailsSent != 0 || sum.Skipped != 1 {
		t.Fatalf("summary = %+v, want 1 subscriber / 0 emails / 1 skipped", sum)
	}
}

// A failed send must not advance the cursor, or the postings it covered are
// never told to anyone.
func TestDigestKeepsCursorWhenSendFails(t *testing.T) {
	srv := setup(t)
	enrichAll(t, srv)
	confirmSubscriber(t, srv, "bounce@example.com")
	srv.mailer = failingMailer{}

	if _, err := srv.RunDigests(context.Background()); err != nil {
		t.Fatalf("run digests: %v", err)
	}

	// The provider recovers; the same postings must still be pending.
	mail := &captureMailer{}
	srv.mailer = mail
	sum, err := srv.RunDigests(context.Background())
	if err != nil {
		t.Fatalf("retry: %v", err)
	}
	if sum.EmailsSent != 1 || len(mail.digests) != 1 {
		t.Fatalf("postings were lost after a failed send: %+v", sum)
	}
}

type failingMailer struct{}

func (failingMailer) SendLoginLink(context.Context, string, string) error { return nil }
func (failingMailer) SendDigest(context.Context, Subscriber, DigestContent) error {
	return context.DeadlineExceeded
}

func TestDigestGroupsByCompanyAndRendersBothParts(t *testing.T) {
	srv := setup(t)
	ctx := context.Background()
	if _, err := srv.store.pool.Exec(ctx, `
		INSERT INTO jobs (company, job_id, title, url, first_seen_at, last_seen_at, is_seed) VALUES
			('Acme','7','Staff Software Engineer','https://acme.example/7','2026-08-03',now(),false),
			('Beta','8','Software Developer','https://beta.example/8','2026-08-03',now(),false)`,
	); err != nil {
		t.Fatalf("insert: %v", err)
	}
	enrichAll(t, srv)
	confirmSubscriber(t, srv, "grouped@example.com")

	mail := &captureMailer{}
	srv.mailer = mail
	if _, err := srv.RunDigests(ctx); err != nil {
		t.Fatalf("run digests: %v", err)
	}
	if len(mail.digests) != 1 {
		t.Fatalf("captured %d digests, want 1", len(mail.digests))
	}
	c := mail.digests[0].content

	seen := map[string]int{}
	for _, company := range c.Companies {
		seen[company.Company] = len(company.Jobs)
	}
	if seen["Acme"] != 2 || seen["Beta"] != 1 {
		t.Fatalf("grouping = %v, want Acme:2 Beta:1", seen)
	}

	html, text := digestHTML(c), digestText(c)
	for _, want := range []string{"Staff Software Engineer", "Software Developer", "Unsubscribe"} {
		if !strings.Contains(html, want) {
			t.Errorf("html missing %q", want)
		}
	}
	if !strings.Contains(text, "Unsubscribe:") {
		t.Error("text part missing the opt-out")
	}
	// The subject names companies rather than counting anonymous "matches".
	if subj := digestSubject(c); !strings.Contains(subj, "Acme") {
		t.Errorf("subject = %q, want it to name a company", subj)
	}
}

func TestUnsubscribeLinkStopsDigestsAndIsIdempotent(t *testing.T) {
	srv := setup(t)
	t.Setenv("JOBWATCH_LINK_SECRET", "test-secret")
	enrichAll(t, srv)
	userID, _ := confirmSubscriber(t, srv, "optout@example.com")

	link := srv.UnsubscribeURL(userID)
	target := link[strings.Index(link, "/u?"):]

	// The mail provider's automated one-click POST must work without a session.
	if rec := do(t, srv, "", http.MethodPost, target, ""); rec.Code != http.StatusOK {
		t.Fatalf("one-click POST: status %d: %s", rec.Code, rec.Body.String())
	}
	if rec := get(t, srv, "", target); rec.Code != http.StatusOK {
		t.Fatalf("repeat unsubscribe: status %d", rec.Code)
	}

	mail := &captureMailer{}
	srv.mailer = mail
	if _, err := srv.RunDigests(context.Background()); err != nil {
		t.Fatalf("run digests: %v", err)
	}
	if len(mail.digests) != 0 {
		t.Fatalf("still emailing after unsubscribe: %+v", mail.digests)
	}

	// A tampered signature is refused.
	if rec := get(t, srv, "", "/u?i="+userID+"&s=deadbeef"); rec.Code != http.StatusBadRequest {
		t.Fatalf("forged unsubscribe accepted: status %d", rec.Code)
	}
}

// The "and N more" line must be the real remainder. Inferring it from an
// over-fetch of limit+1 can only ever say "and 1 more", which for a subscriber
// with no level filter understates the truth by orders of magnitude.
func TestDigestOverflowCountsTheRealRemainder(t *testing.T) {
	srv := setup(t)
	ctx := context.Background()

	// Comfortably more than one email holds.
	for i := range digestMaxJobs + 25 {
		if _, err := srv.store.pool.Exec(ctx, `
			INSERT INTO jobs (company, job_id, title, url, first_seen_at, last_seen_at, is_seed)
			VALUES ('Acme', $1, 'Software Engineer', 'https://acme.example/x', '2026-08-03', now(), false)`,
			"bulk-"+strconv.Itoa(i),
		); err != nil {
			t.Fatalf("insert: %v", err)
		}
	}
	enrichAll(t, srv)
	confirmSubscriber(t, srv, "bulk@example.com")

	mail := &captureMailer{}
	srv.mailer = mail
	if _, err := srv.RunDigests(ctx); err != nil {
		t.Fatalf("run digests: %v", err)
	}
	if len(mail.digests) != 1 {
		t.Fatalf("captured %d digests, want 1", len(mail.digests))
	}

	c := mail.digests[0].content
	if c.Total != digestMaxJobs {
		t.Fatalf("carried %d roles, want the cap of %d", c.Total, digestMaxJobs)
	}
	// 25 bulk rows beyond the cap, plus the fixture's own Frontend Engineer.
	if c.Overflow != 26 {
		t.Fatalf("overflow = %d, want 26 — the real remainder, not an over-fetch of 1", c.Overflow)
	}
	if !strings.Contains(digestHTML(c), "and 26 more") {
		t.Error("email does not state the real remainder")
	}
}

// Ingestion runs every couple of hours; a person must still be emailed about
// once a day. Without this gate a two-hourly pipeline is a two-hourly
// newsletter, which burns the sending domain and the subscriber list with it.
func TestDigestRunsOftenButEmailsOncePerInterval(t *testing.T) {
	srv := setup(t)
	ctx := context.Background()
	enrichAll(t, srv)
	confirmSubscriber(t, srv, "cadence@example.com")

	mail := &captureMailer{}
	srv.mailer = mail

	if _, err := srv.RunDigests(ctx); err != nil {
		t.Fatalf("first run: %v", err)
	}
	if len(mail.digests) != 1 {
		t.Fatalf("first run sent %d digests, want 1", len(mail.digests))
	}

	// A posting arrives, and the pipeline runs again two hours later. There is
	// something new to say, but it is not yet this subscriber's turn.
	if _, err := srv.store.pool.Exec(ctx, `
		INSERT INTO jobs (company, job_id, title, url, first_seen_at, last_seen_at, is_seed)
		VALUES ('Acme','later','Senior Software Engineer','https://acme.example/later',now(),now(),false)`,
	); err != nil {
		t.Fatalf("insert: %v", err)
	}
	enrichAll(t, srv)

	for range 11 { // the rest of a day's two-hourly runs
		if _, err := srv.RunDigests(ctx); err != nil {
			t.Fatalf("subsequent run: %v", err)
		}
	}
	if len(mail.digests) != 1 {
		t.Fatalf("sent %d digests across a day of two-hourly runs, want 1", len(mail.digests))
	}

	// Once the interval has elapsed, the accumulated posting goes out — skipping
	// a run must defer a digest, never drop the postings it would have carried.
	if _, err := srv.store.pool.Exec(ctx,
		`UPDATE users SET last_digest_at = now() - interval '24 hours'
		 WHERE email = 'cadence@example.com'`); err != nil {
		t.Fatalf("age the cursor: %v", err)
	}
	if _, err := srv.RunDigests(ctx); err != nil {
		t.Fatalf("run after interval: %v", err)
	}
	if len(mail.digests) != 2 {
		t.Fatalf("sent %d digests, want 2 once the interval elapsed", len(mail.digests))
	}
	if ids := mail.digests[1].jobIDs(); len(ids) != 1 || ids[0] != "later" {
		t.Fatalf("second digest carried %v, want the posting that accumulated", ids)
	}
}

// A zero interval means "every run", which is what a future per-subscriber
// faster tier would set. It must not be read as "never".
func TestZeroDigestIntervalSendsEveryRun(t *testing.T) {
	srv := setup(t)
	ctx := context.Background()
	srv.digestInterval = 0
	enrichAll(t, srv)
	confirmSubscriber(t, srv, "instant@example.com")

	mail := &captureMailer{}
	srv.mailer = mail
	if _, err := srv.RunDigests(ctx); err != nil {
		t.Fatalf("first run: %v", err)
	}

	if _, err := srv.store.pool.Exec(ctx, `
		INSERT INTO jobs (company, job_id, title, url, first_seen_at, last_seen_at, is_seed)
		VALUES ('Acme','fast','Software Engineer','https://acme.example/fast',now(),now(),false)`,
	); err != nil {
		t.Fatalf("insert: %v", err)
	}
	enrichAll(t, srv)

	if _, err := srv.RunDigests(ctx); err != nil {
		t.Fatalf("second run: %v", err)
	}
	if len(mail.digests) != 2 {
		t.Fatalf("sent %d digests with a zero interval, want 2", len(mail.digests))
	}
}
