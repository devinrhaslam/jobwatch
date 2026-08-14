package server

import (
	"context"
	"encoding/json"
	"net/http"
	"os"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

// stubClassifier drops any job whose title contains one of `off`, and counts how
// many times it was called — so a test can assert the verdict cache prevented a
// second classification.
type stubClassifier struct {
	off   []string
	calls int
}

func (c *stubClassifier) Classify(_ context.Context, _ string, jobs []Job) ([]Verdict, error) {
	c.calls++
	out := make([]Verdict, len(jobs))
	for i, j := range jobs {
		keep := true
		for _, marker := range c.off {
			if strings.Contains(j.Title, marker) {
				keep = false
			}
		}
		out[i] = Verdict{Keep: keep, Reason: "stub"}
	}
	return out, nil
}

// backdateWatchlist moves a user's added_at into the past so the fixture's
// 2026 jobs (all first-seen before test time) qualify as candidates.
func backdateWatchlist(t *testing.T, userID, when string) {
	t.Helper()
	pool, err := pgxpool.New(context.Background(), os.Getenv("JOBWATCH_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatalf("connect: %v", err)
	}
	defer pool.Close()
	if _, err := pool.Exec(context.Background(),
		`UPDATE user_companies SET added_at = $2 WHERE user_id = $1`, userID, when); err != nil {
		t.Fatalf("backdate: %v", err)
	}
}

func matchUser(t *testing.T, srv *Server, userID string) MatchResult {
	t.Helper()
	rec := do(t, srv, http.MethodPost, "/users/"+userID+"/match", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("match: status %d: %s", rec.Code, rec.Body.String())
	}
	var result MatchResult
	if err := json.Unmarshal(rec.Body.Bytes(), &result); err != nil {
		t.Fatalf("decode: %v", err)
	}
	return result
}

// The fixture (from setup) seeds Acme "1" Backend Engineer @ 2026-01-01 and
// Acme "2" Frontend Engineer @ 2026-08-01.
func matchReadyUser(t *testing.T, srv *Server, stub *stubClassifier, email string) string {
	t.Helper()
	user := createUser(t, srv, email)
	if rec := do(t, srv, http.MethodPut, "/users/"+user.ID+"/profile",
		`{"profile":"Senior backend engineer, US-remote"}`); rec.Code != http.StatusNoContent {
		t.Fatalf("set profile: %d", rec.Code)
	}
	if rec := do(t, srv, http.MethodPut, "/users/"+user.ID+"/watchlist",
		`{"companies":["Acme"]}`); rec.Code != http.StatusNoContent {
		t.Fatalf("set watchlist: %d", rec.Code)
	}
	srv.classifier = stub
	return user.ID
}

func TestMatchRequiresAProfile(t *testing.T) {
	srv := setup(t)
	user := createUser(t, srv, "np@example.com")
	rec := do(t, srv, http.MethodPost, "/users/"+user.ID+"/match", "")
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status %d, want 400 (no profile)", rec.Code)
	}
}

func TestMatchStagesKeepersAndFiltersDrops(t *testing.T) {
	srv := setup(t)
	stub := &stubClassifier{off: []string{"Frontend"}}
	userID := matchReadyUser(t, srv, stub, "m1@example.com")
	backdateWatchlist(t, userID, "2025-01-01T00:00:00Z")

	result := matchUser(t, srv, userID)
	if result.Evaluated != 2 || result.Kept != 1 {
		t.Fatalf("result = %+v, want evaluated 2 / kept 1", result)
	}

	rec := get(t, srv, "/users/"+userID+"/matches")
	var matches []Match
	json.Unmarshal(rec.Body.Bytes(), &matches)
	if len(matches) != 1 || matches[0].JobID != "1" { // "1" is the Backend Engineer
		t.Fatalf("matches = %+v, want only the backend role", matches)
	}
}

func TestMatchSeedingBoundaryExcludesPreAddJobs(t *testing.T) {
	srv := setup(t)
	stub := &stubClassifier{}
	userID := matchReadyUser(t, srv, stub, "m2@example.com")
	// Added between the two jobs: only the 2026-08-01 one is after this floor.
	backdateWatchlist(t, userID, "2026-03-01T00:00:00Z")

	result := matchUser(t, srv, userID)
	if result.Evaluated != 1 {
		t.Fatalf("evaluated = %d, want 1 (pre-add job excluded)", result.Evaluated)
	}
}

func TestSecondMatchRunReportsNothingNew(t *testing.T) {
	srv := setup(t)
	stub := &stubClassifier{}
	userID := matchReadyUser(t, srv, stub, "m3@example.com")
	backdateWatchlist(t, userID, "2025-01-01T00:00:00Z")

	if first := matchUser(t, srv, userID); first.Evaluated != 2 {
		t.Fatalf("first run evaluated %d, want 2", first.Evaluated)
	}
	if second := matchUser(t, srv, userID); second.Evaluated != 0 {
		t.Fatalf("second run evaluated %d, want 0 (cursor advanced)", second.Evaluated)
	}
}

func TestVerdictCachePreventsReclassification(t *testing.T) {
	srv := setup(t)
	stub := &stubClassifier{}
	userID := matchReadyUser(t, srv, stub, "m4@example.com")
	backdateWatchlist(t, userID, "2025-01-01T00:00:00Z")

	matchUser(t, srv, userID)
	if stub.calls != 1 {
		t.Fatalf("classifier called %d times on first run, want 1", stub.calls)
	}

	// Rewind the cursor so the same jobs are candidates again; the verdict cache
	// should serve them without a second classification.
	pool, _ := pgxpool.New(context.Background(), os.Getenv("JOBWATCH_TEST_DATABASE_URL"))
	defer pool.Close()
	pool.Exec(context.Background(), `UPDATE users SET last_matched_at = NULL WHERE id = $1`, userID)

	matchUser(t, srv, userID)
	if stub.calls != 1 {
		t.Fatalf("classifier called %d times total, want 1 (cache should serve the rerun)", stub.calls)
	}
}
