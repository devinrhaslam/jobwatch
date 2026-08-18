package server

import (
	"context"
	"net/http"
	"net/url"
	"strings"
	"testing"
)

func eventCount(t *testing.T, srv *Server, name string) int {
	t.Helper()
	var n int
	if err := srv.store.pool.QueryRow(context.Background(),
		`SELECT count(*) FROM events WHERE name = $1`, name).Scan(&n); err != nil {
		t.Fatalf("count %s: %v", name, err)
	}
	return n
}

func TestSignupFunnelIsRecorded(t *testing.T) {
	srv := setup(t)
	srv.devAuth = true // returns the magic link in the body

	rec := do(t, srv, "", http.MethodPost, "/auth/request", `{"email":"funnel@example.com"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("auth request: %d: %s", rec.Code, rec.Body.String())
	}
	if got := eventCount(t, srv, EventSignupStarted); got != 1 {
		t.Fatalf("signup_started = %d, want 1", got)
	}
	// Not confirmed until the link is followed — that is the whole point of
	// double opt-in, and the digest must not treat them as a subscriber yet.
	if got := eventCount(t, srv, EventSignupConfirmed); got != 0 {
		t.Fatalf("signup_confirmed = %d before verifying, want 0", got)
	}

	var body struct {
		DevLink string `json:"dev_link"`
	}
	decode(t, rec, &body)
	token := body.DevLink[strings.Index(body.DevLink, "token=")+len("token="):]

	if rec := do(t, srv, "", http.MethodPost, "/auth/verify",
		`{"token":"`+token+`"}`); rec.Code != http.StatusOK {
		t.Fatalf("verify: %d: %s", rec.Code, rec.Body.String())
	}
	if got := eventCount(t, srv, EventSignupConfirmed); got != 1 {
		t.Fatalf("signup_confirmed = %d after verifying, want 1", got)
	}
}

func TestClickRedirectsAndRecords(t *testing.T) {
	srv := setup(t)
	t.Setenv("JOBWATCH_LINK_SECRET", "test-secret")

	dest := "https://acme.example/jobs/1?src=board"
	link := srv.TrackedJobURL(dest, "Acme", "1", "")
	if !strings.Contains(link, "/e/c?") {
		t.Fatalf("tracking not applied: %s", link)
	}

	rec := get(t, srv, "", link[strings.Index(link, "/e/c?"):])
	if rec.Code != http.StatusFound {
		t.Fatalf("status = %d, want 302", rec.Code)
	}
	if got := rec.Header().Get("Location"); got != dest {
		t.Fatalf("redirected to %q, want %q", got, dest)
	}
	if got := eventCount(t, srv, EventJobClicked); got != 1 {
		t.Fatalf("job_clicked = %d, want 1", got)
	}
}

// The redirector must not forward to an arbitrary URL just because someone
// appended one — that would make the domain an open redirect for phishing.
func TestClickRejectsUnsignedDestination(t *testing.T) {
	srv := setup(t)
	t.Setenv("JOBWATCH_LINK_SECRET", "test-secret")

	forged := "/e/c?u=" + url.QueryEscape("aHR0cHM6Ly9ldmlsLmV4YW1wbGU") + "&s=notasignature"
	rec := get(t, srv, "", forged)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("forged link status = %d, want 400", rec.Code)
	}
	if loc := rec.Header().Get("Location"); loc != "" {
		t.Fatalf("forged link redirected to %q", loc)
	}
	if got := eventCount(t, srv, EventJobClicked); got != 0 {
		t.Fatalf("forged click was recorded: %d", got)
	}
}

// Without a signing secret there is no safe way to run a redirector, so links
// must degrade to the plain destination rather than silently breaking.
func TestTrackingDisabledLeavesLinksUntouched(t *testing.T) {
	srv := setup(t)
	t.Setenv("JOBWATCH_LINK_SECRET", "")

	dest := "https://acme.example/jobs/1"
	if got := srv.TrackedJobURL(dest, "Acme", "1", ""); got != dest {
		t.Fatalf("link = %q, want the bare destination %q", got, dest)
	}
	if got := srv.OpenPixelURL("someone"); got != "" {
		t.Fatalf("pixel URL = %q, want empty", got)
	}
}

func TestOpenPixelAlwaysReturnsAnImage(t *testing.T) {
	srv := setup(t)
	t.Setenv("JOBWATCH_LINK_SECRET", "test-secret")

	// A bad signature still gets a valid image: a broken-image box in someone's
	// inbox is a worse outcome than a missing metric.
	rec := get(t, srv, "", "/e/o.gif?i=nobody&s=wrong")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "image/gif" {
		t.Fatalf("content-type = %q", ct)
	}
	if got := eventCount(t, srv, EventDigestOpened); got != 0 {
		t.Fatalf("unsigned open was recorded: %d", got)
	}
}

func TestPreferencesValidateLevels(t *testing.T) {
	srv := setup(t)
	_, token := signIn(t, srv, "prefs@example.com")

	if rec := do(t, srv, token, http.MethodPut, "/me/preferences",
		`{"levels":["senior","intern"],"us_only":true,"remote_only":false}`); rec.Code != http.StatusNoContent {
		t.Fatalf("valid prefs: %d: %s", rec.Code, rec.Body.String())
	}
	// An unknown level would sit in the column filtering nothing, which looks
	// like a working setting and is not one.
	rec := do(t, srv, token, http.MethodPut, "/me/preferences",
		`{"levels":["wizard"],"us_only":true,"remote_only":false}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("bogus level accepted: %d", rec.Code)
	}

	var view UserView
	decode(t, get(t, srv, token, "/me"), &view)
	if len(view.Levels) != 2 {
		t.Fatalf("levels = %v, want the two valid ones", view.Levels)
	}
}
