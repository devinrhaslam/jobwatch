package server

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Integration tests, gated on JOBWATCH_TEST_DATABASE_URL against a throwaway
// database — the Go mirror of the Python store's gating, so `go test ./...`
// stays green without a database.
//
//	JOBWATCH_TEST_DATABASE_URL=postgresql://jobwatch:jobwatch@localhost:5432/jobwatch_test \
//	    go test ./...

func testDSN(t *testing.T) string {
	t.Helper()
	dsn := os.Getenv("JOBWATCH_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("set JOBWATCH_TEST_DATABASE_URL to run backend integration tests")
	}
	return dsn
}

const schema = `
CREATE TABLE IF NOT EXISTS jobs (
	company text NOT NULL, job_id text NOT NULL, title text NOT NULL,
	url text NOT NULL, location text, posted_date text,
	first_seen_at timestamptz NOT NULL DEFAULT now(),
	last_seen_at timestamptz NOT NULL DEFAULT now(),
	is_seed boolean NOT NULL DEFAULT false,
	PRIMARY KEY (company, job_id));
CREATE TABLE IF NOT EXISTS job_enrichment (
	company text NOT NULL, job_id text NOT NULL, title_hash text NOT NULL,
	is_swe boolean NOT NULL, level text NOT NULL, is_us boolean NOT NULL,
	is_remote boolean NOT NULL, reason text NOT NULL DEFAULT '',
	judged_at timestamptz NOT NULL DEFAULT now(),
	PRIMARY KEY (company, job_id));
CREATE TABLE IF NOT EXISTS company_runs (
	id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, company text NOT NULL,
	ran_at timestamptz NOT NULL DEFAULT now(), status text NOT NULL,
	jobs_read integer NOT NULL DEFAULT 0, jobs_new integer NOT NULL DEFAULT 0, error text);
CREATE TABLE IF NOT EXISTS users (
	id uuid PRIMARY KEY DEFAULT gen_random_uuid(), email text NOT NULL UNIQUE,
	created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS user_profiles (
	user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
	profile_text text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS user_companies (
	user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	company text NOT NULL, added_at timestamptz NOT NULL DEFAULT now(),
	PRIMARY KEY (user_id, company));
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_matched_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_digest_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS confirmed_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS unsubscribed_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS levels text[] NOT NULL DEFAULT '{}';
ALTER TABLE users ADD COLUMN IF NOT EXISTS us_only boolean NOT NULL DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS remote_only boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS events (
	id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name text NOT NULL,
	user_id uuid REFERENCES users(id) ON DELETE SET NULL,
	props jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS fit_verdicts (
	profile_hash text NOT NULL, company text NOT NULL, title text NOT NULL,
	location text NOT NULL DEFAULT '', keep boolean NOT NULL, reason text NOT NULL DEFAULT '',
	created_at timestamptz NOT NULL DEFAULT now(),
	PRIMARY KEY (profile_hash, company, title, location));
CREATE TABLE IF NOT EXISTS matches (
	user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	company text NOT NULL, job_id text NOT NULL, reason text NOT NULL DEFAULT '',
	matched_at timestamptz NOT NULL DEFAULT now(),
	PRIMARY KEY (user_id, company, job_id));
CREATE TABLE IF NOT EXISTS login_tokens (
	token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	expires_at timestamptz NOT NULL, used_at timestamptz);
CREATE TABLE IF NOT EXISTS sessions (
	token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL);
TRUNCATE jobs, job_enrichment, company_runs, users, fit_verdicts, matches,
	login_tokens, sessions, events CASCADE;`

// setup resets the schema, seeds a fixed fixture, and returns a live Server.
func setup(t *testing.T) *Server {
	t.Helper()
	dsn := testDSN(t)
	ctx := context.Background()

	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer pool.Close()

	// pgx runs a multi-statement, parameter-free query over the simple protocol.
	if _, err := pool.Exec(ctx, schema); err != nil {
		t.Fatalf("schema: %v", err)
	}

	early := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	late := time.Date(2026, 8, 1, 0, 0, 0, 0, time.UTC)
	// is_seed mirrors what the ingester records: a company's first run writes
	// its whole board at once, and those rows are back-catalogue, not news.
	if _, err := pool.Exec(ctx, `
		INSERT INTO jobs (company, job_id, title, url, first_seen_at, last_seen_at, is_seed) VALUES
			('Acme', '1', 'Backend Engineer',  'https://acme.example/1', $1, $1, true),
			('Acme', '2', 'Frontend Engineer', 'https://acme.example/2', $2, $2, false),
			('Beta', '9', 'Site Reliability',  'https://beta.example/9', $1, $1, true)`,
		early, late,
	); err != nil {
		t.Fatalf("seed: %v", err)
	}

	srv, err := New(ctx, dsn)
	if err != nil {
		t.Fatalf("server: %v", err)
	}
	// Never reach the network from a test: both model-backed seams get stubs.
	srv.classifier = &stubClassifier{}
	srv.enricher = &stubEnricher{}
	t.Cleanup(srv.Close)
	return srv
}

// enrichAll runs the real enrichment pass over the fixture, so tests exercise
// the same path production does rather than hand-writing verdict rows.
func enrichAll(t *testing.T, srv *Server) {
	t.Helper()
	if _, err := srv.EnrichNew(context.Background(), time.Unix(0, 0).UTC(), 500); err != nil {
		t.Fatalf("enrich: %v", err)
	}
}

// confirmSubscriber signs in an address and marks it confirmed with a cursor far
// enough back that the fixture's postings are in range.
func confirmSubscriber(t *testing.T, srv *Server, email string) (userID, token string) {
	t.Helper()
	userID, token = signIn(t, srv, email)
	pool, err := pgxpool.New(context.Background(), os.Getenv("JOBWATCH_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer pool.Close()
	if _, err := pool.Exec(context.Background(),
		`UPDATE users SET confirmed_at = '2025-01-01T00:00:00Z' WHERE id = $1`, userID); err != nil {
		t.Fatalf("confirm: %v", err)
	}
	return userID, token
}

// get and do send a request, optionally authenticated with a bearer token
// (pass "" for none).
func get(t *testing.T, srv *Server, token, target string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, target, nil)
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	rec := httptest.NewRecorder()
	srv.Routes().ServeHTTP(rec, req)
	return rec
}

func do(t *testing.T, srv *Server, token, method, target, body string) *httptest.ResponseRecorder {
	t.Helper()
	var r io.Reader
	if body != "" {
		r = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, target, r)
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	rec := httptest.NewRecorder()
	srv.Routes().ServeHTTP(rec, req)
	return rec
}

// decode unmarshals a recorded JSON response, failing the test on bad JSON.
func decode(t *testing.T, rec *httptest.ResponseRecorder, v any) {
	t.Helper()
	if err := json.Unmarshal(rec.Body.Bytes(), v); err != nil {
		t.Fatalf("decode %s: %v", rec.Body.String(), err)
	}
}

// signIn creates (or finds) the account and mints a session directly through the
// store, bypassing the email round-trip so tests set up an authenticated user in
// one step. Returns the user id and the raw session token.
func signIn(t *testing.T, srv *Server, email string) (userID, token string) {
	t.Helper()
	ctx := context.Background()
	user, err := srv.store.UpsertUser(ctx, email)
	if err != nil {
		t.Fatalf("signIn upsert: %v", err)
	}
	raw, hash := newToken()
	if err := srv.store.CreateSession(ctx, user.ID, hash, time.Now().Add(time.Hour)); err != nil {
		t.Fatalf("signIn session: %v", err)
	}
	return user.ID, raw
}

func TestCompaniesListsDistinctSorted(t *testing.T) {
	srv := setup(t)
	rec := get(t, srv, "", "/companies")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	var companies []string
	if err := json.Unmarshal(rec.Body.Bytes(), &companies); err != nil {
		t.Fatalf("decode: %v", err)
	}
	want := []string{"Acme", "Beta"}
	if len(companies) != 2 || companies[0] != want[0] || companies[1] != want[1] {
		t.Fatalf("companies = %v, want %v", companies, want)
	}
}

func TestJobsForCompanyNewestFirst(t *testing.T) {
	srv := setup(t)
	rec := get(t, srv, "", "/jobs?company=Acme")
	var jobs []Job
	if err := json.Unmarshal(rec.Body.Bytes(), &jobs); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(jobs) != 2 {
		t.Fatalf("got %d jobs, want 2", len(jobs))
	}
	if jobs[0].JobID != "2" {
		t.Fatalf("newest-first broken: first job is %s, want 2", jobs[0].JobID)
	}
}

func TestJobsSinceFiltersToNewer(t *testing.T) {
	srv := setup(t)
	rec := get(t, srv, "", "/jobs?company=Acme&since=2026-06-01T00:00:00Z")
	var jobs []Job
	if err := json.Unmarshal(rec.Body.Bytes(), &jobs); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(jobs) != 1 || jobs[0].JobID != "2" {
		t.Fatalf("since filter = %v, want only job 2", jobs)
	}
}

func TestJobsRejectsBadSince(t *testing.T) {
	srv := setup(t)
	rec := get(t, srv, "", "/jobs?since=not-a-date")
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestHealthReportsCorpusSize(t *testing.T) {
	srv := setup(t)
	rec := get(t, srv, "", "/health")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	var h Health
	if err := json.Unmarshal(rec.Body.Bytes(), &h); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if h.Status != "ok" || h.Jobs != 3 || h.Companies != 2 {
		t.Fatalf("health = %+v, want ok/3/2", h)
	}
	if len(h.Problems) != 0 {
		t.Fatalf("problems = %v, want none", h.Problems)
	}
}

func TestSoftwareFeedExcludesSeedsAndNonEngineering(t *testing.T) {
	srv := setup(t)
	ctx := context.Background()

	// Two more post-seed Acme roles: one engineering (kept), one not (dropped).
	if _, err := srv.store.pool.Exec(ctx, `
		INSERT INTO jobs (company, job_id, title, url, first_seen_at, last_seen_at, is_seed) VALUES
			('Acme','3','Platform Engineer','https://acme.example/3','2026-08-02',now(),false),
			('Acme','4','Sales Manager','https://acme.example/4','2026-08-02',now(),false)`,
	); err != nil {
		t.Fatalf("insert: %v", err)
	}
	enrichAll(t, srv)

	rec := get(t, srv, "", "/feed?since=2020-01-01T00:00:00Z")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	var jobs []JobView
	if err := json.Unmarshal(rec.Body.Bytes(), &jobs); err != nil {
		t.Fatalf("decode: %v", err)
	}
	titles := map[string]bool{}
	for _, j := range jobs {
		titles[j.Title] = true
	}

	if !titles["Frontend Engineer"] || !titles["Platform Engineer"] {
		t.Fatalf("post-seed engineering roles missing: %v", jobs)
	}
	// Seeded rows are back-catalogue, not news.
	if titles["Backend Engineer"] || titles["Site Reliability"] {
		t.Fatalf("a seed job leaked into the feed: %v", jobs)
	}
	if titles["Sales Manager"] {
		t.Fatalf("non-engineering role leaked into the feed: %v", jobs)
	}
}

// The feed reads enrichment written by the cron; it must never call a model in
// the request path, however cold the cache is.
func TestFeedNeverClassifiesInTheRequestPath(t *testing.T) {
	srv := setup(t)
	stub := &stubEnricher{}
	srv.enricher = stub

	// Deliberately no enrichment pass first: unjudged postings are invisible
	// rather than an excuse to classify while someone waits on a page load.
	if rec := get(t, srv, "", "/feed?since=2020-01-01T00:00:00Z"); rec.Code != http.StatusOK {
		t.Fatalf("feed status = %d", rec.Code)
	}
	if stub.calls != 0 {
		t.Fatalf("feed enriched in the request path: calls = %d, want 0", stub.calls)
	}

	enrichAll(t, srv)
	if stub.calls != 1 {
		t.Fatalf("cron pass made %d calls, want 1", stub.calls)
	}
	rec := get(t, srv, "", "/feed?since=2020-01-01T00:00:00Z")
	var jobs []JobView
	if err := json.Unmarshal(rec.Body.Bytes(), &jobs); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(jobs) == 0 {
		t.Fatal("feed empty after enrichment")
	}
	if stub.calls != 1 {
		t.Fatalf("serving the feed enriched again: calls = %d, want 1", stub.calls)
	}
	// The API resolves the company logo so the web app and the email agree.
	if jobs[0].LogoURL == "" {
		t.Error("feed rows carry no logo_url")
	}
}

func TestUserSignupIsIdempotentOnEmail(t *testing.T) {
	srv := setup(t)
	ctx := context.Background()
	first, err := srv.store.UpsertUser(ctx, "Dev@Example.com")
	if err != nil {
		t.Fatalf("upsert: %v", err)
	}
	second, err := srv.store.UpsertUser(ctx, "dev@example.com") // same person, different case
	if err != nil {
		t.Fatalf("upsert: %v", err)
	}
	if first.ID != second.ID {
		t.Fatalf("signup created two accounts: %s vs %s", first.ID, second.ID)
	}
	if second.Email != "dev@example.com" {
		t.Fatalf("email not normalised: %q", second.Email)
	}
}

func TestMagicLinkFlowIssuesAWorkingSession(t *testing.T) {
	srv := setup(t)
	srv.devAuth = true // return the link in the body so the test can follow it

	rec := do(t, srv, "", http.MethodPost, "/auth/request", `{"email":"login@example.com"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("request: status %d: %s", rec.Code, rec.Body.String())
	}
	var reqResp struct {
		DevLink string `json:"dev_link"`
	}
	json.Unmarshal(rec.Body.Bytes(), &reqResp)
	idx := strings.Index(reqResp.DevLink, "token=")
	if idx < 0 {
		t.Fatalf("no token in dev link: %q", reqResp.DevLink)
	}
	loginToken := reqResp.DevLink[idx+len("token="):]

	rec = do(t, srv, "", http.MethodPost, "/auth/verify", `{"token":"`+loginToken+`"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("verify: status %d: %s", rec.Code, rec.Body.String())
	}
	var verifyResp struct {
		Token string   `json:"token"`
		User  UserView `json:"user"`
	}
	json.Unmarshal(rec.Body.Bytes(), &verifyResp)
	if verifyResp.Token == "" || verifyResp.User.Email != "login@example.com" {
		t.Fatalf("verify response = %+v", verifyResp)
	}

	// The session token authenticates /me.
	if rec := get(t, srv, verifyResp.Token, "/me"); rec.Code != http.StatusOK {
		t.Fatalf("GET /me with session: status %d", rec.Code)
	}

	// A login token is single-use: verifying it again fails.
	if rec := do(t, srv, "", http.MethodPost, "/auth/verify", `{"token":"`+loginToken+`"}`); rec.Code != http.StatusUnauthorized {
		t.Fatalf("reused login token: status %d, want 401", rec.Code)
	}
}

func TestMeRequiresAuthentication(t *testing.T) {
	srv := setup(t)
	if rec := get(t, srv, "", "/me"); rec.Code != http.StatusUnauthorized {
		t.Fatalf("no token: status %d, want 401", rec.Code)
	}
	if rec := get(t, srv, "bogus-token", "/me"); rec.Code != http.StatusUnauthorized {
		t.Fatalf("bad token: status %d, want 401", rec.Code)
	}
}

func TestLogoutRevokesTheSession(t *testing.T) {
	srv := setup(t)
	_, token := signIn(t, srv, "out@example.com")
	if rec := get(t, srv, token, "/me"); rec.Code != http.StatusOK {
		t.Fatalf("pre-logout /me: status %d", rec.Code)
	}
	if rec := do(t, srv, token, http.MethodPost, "/auth/logout", ""); rec.Code != http.StatusNoContent {
		t.Fatalf("logout: status %d", rec.Code)
	}
	if rec := get(t, srv, token, "/me"); rec.Code != http.StatusUnauthorized {
		t.Fatalf("post-logout /me: status %d, want 401", rec.Code)
	}
}

func TestDeleteMeWipesTheAccountAndSession(t *testing.T) {
	srv := setup(t)
	userID, token := signIn(t, srv, "gone@example.com")
	do(t, srv, token, http.MethodPut, "/me/profile", `{"profile":"my resume text"}`)
	do(t, srv, token, http.MethodPut, "/me/watchlist", `{"companies":["Acme"]}`)

	if rec := do(t, srv, token, http.MethodDelete, "/me", ""); rec.Code != http.StatusNoContent {
		t.Fatalf("delete: status %d", rec.Code)
	}
	// The session cascaded away, so the token no longer authenticates.
	if rec := get(t, srv, token, "/me"); rec.Code != http.StatusUnauthorized {
		t.Fatalf("post-delete /me: status %d, want 401", rec.Code)
	}
	// And the personal data is gone.
	if wl, _ := srv.store.Watchlist(context.Background(), userID); len(wl) != 0 {
		t.Fatalf("watchlist survived deletion: %v", wl)
	}
}

func TestSetProfileReadsBackOnMe(t *testing.T) {
	srv := setup(t)
	_, token := signIn(t, srv, "a@example.com")

	if rec := do(t, srv, token, http.MethodPut, "/me/profile",
		`{"profile":"Senior backend engineer, US-remote"}`); rec.Code != http.StatusNoContent {
		t.Fatalf("set profile: status %d", rec.Code)
	}

	rec := get(t, srv, token, "/me")
	var view UserView
	if err := json.Unmarshal(rec.Body.Bytes(), &view); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if view.Profile == nil || *view.Profile != "Senior backend engineer, US-remote" {
		t.Fatalf("profile = %v", view.Profile)
	}
}

func TestSetWatchlistReplacesAndValidates(t *testing.T) {
	srv := setup(t)
	_, token := signIn(t, srv, "b@example.com")

	if rec := do(t, srv, token, http.MethodPut, "/me/watchlist",
		`{"companies":["Acme"]}`); rec.Code != http.StatusNoContent {
		t.Fatalf("set [Acme]: status %d: %s", rec.Code, rec.Body.String())
	}
	if rec := do(t, srv, token, http.MethodPut, "/me/watchlist",
		`{"companies":["Acme","Beta"]}`); rec.Code != http.StatusNoContent {
		t.Fatalf("set [Acme,Beta]: status %d", rec.Code)
	}

	rec := get(t, srv, token, "/me")
	var view UserView
	json.Unmarshal(rec.Body.Bytes(), &view)
	if len(view.Watchlist) != 2 || view.Watchlist[0] != "Acme" || view.Watchlist[1] != "Beta" {
		t.Fatalf("watchlist = %v", view.Watchlist)
	}

	// An untracked company is rejected, and the watchlist is left unchanged.
	rec = do(t, srv, token, http.MethodPut, "/me/watchlist",
		`{"companies":["Nonexistent Co"]}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("untracked company: status %d, want 400", rec.Code)
	}
}

// The seeding boundary: re-saving a watchlist that still contains a company must
// not reset its added_at, or a user would be re-alerted about that company's
// back-catalogue every time they edit their list.
func TestWatchlistResavePreservesAddedAt(t *testing.T) {
	srv := setup(t)
	userID, token := signIn(t, srv, "c@example.com")

	do(t, srv, token, http.MethodPut, "/me/watchlist", `{"companies":["Acme"]}`)
	original := addedAt(t, userID, "Acme")

	// Re-save with Acme still present plus a new company.
	do(t, srv, token, http.MethodPut, "/me/watchlist", `{"companies":["Acme","Beta"]}`)
	after := addedAt(t, userID, "Acme")

	if !original.Equal(after) {
		t.Fatalf("Acme added_at moved on resave: %s -> %s", original, after)
	}
	if betaAdded := addedAt(t, userID, "Beta"); !betaAdded.After(original) {
		t.Fatalf("Beta added_at %s should be after Acme's %s", betaAdded, original)
	}
}

func addedAt(t *testing.T, userID, company string) time.Time {
	t.Helper()
	pool, err := pgxpool.New(context.Background(), os.Getenv("JOBWATCH_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer pool.Close()
	var ts time.Time
	if err := pool.QueryRow(context.Background(),
		`SELECT added_at FROM user_companies WHERE user_id = $1 AND company = $2`,
		userID, company,
	).Scan(&ts); err != nil {
		t.Fatalf("added_at(%s): %v", company, err)
	}
	return ts
}
