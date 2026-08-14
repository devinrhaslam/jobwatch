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
TRUNCATE jobs, company_runs, users CASCADE;`

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
	if _, err := pool.Exec(ctx, `
		INSERT INTO jobs (company, job_id, title, url, first_seen_at, last_seen_at) VALUES
			('Acme', '1', 'Backend Engineer',  'https://acme.example/1', $1, $1),
			('Acme', '2', 'Frontend Engineer', 'https://acme.example/2', $2, $2),
			('Beta', '9', 'Site Reliability',  'https://beta.example/9', $1, $1)`,
		early, late,
	); err != nil {
		t.Fatalf("seed: %v", err)
	}

	srv, err := New(ctx, dsn)
	if err != nil {
		t.Fatalf("server: %v", err)
	}
	t.Cleanup(srv.Close)
	return srv
}

func get(t *testing.T, srv *Server, target string) *httptest.ResponseRecorder {
	t.Helper()
	rec := httptest.NewRecorder()
	srv.Routes().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, target, nil))
	return rec
}

func do(t *testing.T, srv *Server, method, target, body string) *httptest.ResponseRecorder {
	t.Helper()
	var r io.Reader
	if body != "" {
		r = strings.NewReader(body)
	}
	rec := httptest.NewRecorder()
	srv.Routes().ServeHTTP(rec, httptest.NewRequest(method, target, r))
	return rec
}

func createUser(t *testing.T, srv *Server, email string) User {
	t.Helper()
	rec := do(t, srv, http.MethodPost, "/users", `{"email":"`+email+`"}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("create user: status %d: %s", rec.Code, rec.Body.String())
	}
	var u User
	if err := json.Unmarshal(rec.Body.Bytes(), &u); err != nil {
		t.Fatalf("decode user: %v", err)
	}
	return u
}

func TestCompaniesListsDistinctSorted(t *testing.T) {
	srv := setup(t)
	rec := get(t, srv, "/companies")
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
	rec := get(t, srv, "/jobs?company=Acme")
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
	rec := get(t, srv, "/jobs?company=Acme&since=2026-06-01T00:00:00Z")
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
	rec := get(t, srv, "/jobs?since=not-a-date")
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", rec.Code)
	}
}

func TestHealthReportsCorpusSize(t *testing.T) {
	srv := setup(t)
	rec := get(t, srv, "/health")
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

func TestUserSignupIsIdempotentOnEmail(t *testing.T) {
	srv := setup(t)
	first := createUser(t, srv, "Dev@Example.com")
	second := createUser(t, srv, "dev@example.com") // different case, same person
	if first.ID != second.ID {
		t.Fatalf("signup created two accounts: %s vs %s", first.ID, second.ID)
	}
	if second.Email != "dev@example.com" {
		t.Fatalf("email not normalised: %q", second.Email)
	}
}

func TestSetProfileReadsBackOnUserView(t *testing.T) {
	srv := setup(t)
	user := createUser(t, srv, "a@example.com")

	rec := do(t, srv, http.MethodPut, "/users/"+user.ID+"/profile",
		`{"profile":"Senior backend engineer, US-remote"}`)
	if rec.Code != http.StatusNoContent {
		t.Fatalf("set profile: status %d", rec.Code)
	}

	rec = get(t, srv, "/users/"+user.ID)
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
	user := createUser(t, srv, "b@example.com")

	if rec := do(t, srv, http.MethodPut, "/users/"+user.ID+"/watchlist",
		`{"companies":["Acme"]}`); rec.Code != http.StatusNoContent {
		t.Fatalf("set [Acme]: status %d: %s", rec.Code, rec.Body.String())
	}
	if rec := do(t, srv, http.MethodPut, "/users/"+user.ID+"/watchlist",
		`{"companies":["Acme","Beta"]}`); rec.Code != http.StatusNoContent {
		t.Fatalf("set [Acme,Beta]: status %d", rec.Code)
	}

	rec := get(t, srv, "/users/"+user.ID)
	var view UserView
	json.Unmarshal(rec.Body.Bytes(), &view)
	if len(view.Watchlist) != 2 || view.Watchlist[0] != "Acme" || view.Watchlist[1] != "Beta" {
		t.Fatalf("watchlist = %v", view.Watchlist)
	}

	// An untracked company is rejected, and the watchlist is left unchanged.
	rec = do(t, srv, http.MethodPut, "/users/"+user.ID+"/watchlist",
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
	user := createUser(t, srv, "c@example.com")

	do(t, srv, http.MethodPut, "/users/"+user.ID+"/watchlist", `{"companies":["Acme"]}`)
	original := addedAt(t, user.ID, "Acme")

	// Re-save with Acme still present plus a new company.
	do(t, srv, http.MethodPut, "/users/"+user.ID+"/watchlist", `{"companies":["Acme","Beta"]}`)
	after := addedAt(t, user.ID, "Acme")

	if !original.Equal(after) {
		t.Fatalf("Acme added_at moved on resave: %s -> %s", original, after)
	}
	if betaAdded := addedAt(t, user.ID, "Beta"); !betaAdded.After(original) {
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
