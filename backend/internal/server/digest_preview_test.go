package server

import (
	"os"
	"testing"
	"time"
)

// TestRenderDigestPreview writes a sample digest to a file so the email can be
// opened in a browser. Email templates cannot be iterated on any other way —
// there is no dev server for an inbox — and this needs no database or API key.
//
//	DIGEST_PREVIEW_OUT=/tmp/digest.html JOBWATCH_LINK_SECRET=dev \
//	    go test ./internal/server/ -run TestRenderDigestPreview -v
//
// The fixture deliberately includes the shapes that break layouts: one company
// with several near-identical reqs (the grouping case), a very long title, and
// an overflow count.
func TestRenderDigestPreview(t *testing.T) {
	out := os.Getenv("DIGEST_PREVIEW_OUT")
	if out == "" {
		t.Skip("set DIGEST_PREVIEW_OUT to render a digest preview")
	}
	loc := func(s string) *string { return &s }
	now := time.Now()
	mk := func(co, id, title, l string, ago time.Duration) Job {
		return Job{Company: co, JobID: id, Title: title, URL: "https://example.com/" + id,
			Location: loc(l), FirstSeenAt: now.Add(-ago)}
	}
	jobs := []Job{
		mk("Microsoft", "1", "Senior Software Engineer", "Redmond, WA", 3*time.Hour),
		mk("Microsoft", "2", "Software Engineer II", "United States, Multiple Locations", 3*time.Hour),
		mk("Microsoft", "3", "Sr. Software Engineer - Azure Storage", "Redmond, WA", 4*time.Hour),
		mk("Stripe", "4", "Backend Engineer, Payments", "Remote (United States)", 7*time.Hour),
		mk("Anthropic", "5", "Software Engineer, Inference", "San Francisco, CA", 11*time.Hour),
		mk("TikTok", "6", "Mobile Software Engineer Intern - 2027 Summer", "San Jose, CA", 26*time.Hour),
	}
	srv := &Server{appBaseURL: "https://jobwatch.example", apiBaseURL: "https://api.jobwatch.example",
		postalAddress: "jobwatch · 123 Example St, Wilmington DE 19801"}
	c := srv.buildDigest(Subscriber{ID: "preview", Email: "you@example.com"}, jobs, 4)
	if err := os.WriteFile(out, []byte(digestHTML(c)), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Logf("subject:   %s", digestSubject(c))
	t.Logf("preheader: %s", digestPreheader(c))
	t.Logf("wrote %s", out)
}
