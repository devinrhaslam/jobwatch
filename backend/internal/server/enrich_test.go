package server

import (
	"context"
	"strings"
	"testing"
)

// stubEnricher reads levels and disciplines out of the title with the same rules
// the prompt describes, which is enough to exercise every filtering path without
// the network. It deliberately answers `unknown` for an unlevelled title, because
// that is the case the filtering logic most needs to get right.
type stubEnricher struct{ calls int }

func (e *stubEnricher) Enrich(_ context.Context, jobs []Job) ([]Enrichment, error) {
	e.calls++
	out := make([]Enrichment, len(jobs))
	for i, j := range jobs {
		t := strings.ToLower(j.Title)
		swe := strings.Contains(t, "engineer") || strings.Contains(t, "software") ||
			strings.Contains(t, "developer") || strings.Contains(t, "reliability")
		// A manager or salesperson is out even when the title says "Engineer".
		if strings.Contains(t, "manager") || strings.Contains(t, "sales") {
			swe = false
		}

		level := LevelUnknown
		switch {
		case strings.Contains(t, "intern"):
			level = LevelIntern
		case strings.Contains(t, "new grad"):
			level = LevelNewGrad
		case strings.Contains(t, "junior"):
			level = LevelJunior
		case strings.Contains(t, "senior"):
			level = LevelSenior
		case strings.Contains(t, "staff"), strings.Contains(t, "principal"):
			level = LevelStaff
		}

		loc := ""
		if j.Location != nil {
			loc = strings.ToLower(*j.Location)
		}
		out[i] = Enrichment{
			IsSWE:    swe,
			Level:    level,
			IsUS:     !strings.Contains(loc, "london") && !strings.Contains(loc, "bengaluru"),
			IsRemote: strings.Contains(loc, "remote"),
			Reason:   "stub",
		}
	}
	return out, nil
}

func TestEnrichmentIsCachedUntilTheTitleChanges(t *testing.T) {
	srv := setup(t)
	stub := &stubEnricher{}
	srv.enricher = stub

	enrichAll(t, srv)
	if stub.calls != 1 {
		t.Fatalf("first pass made %d calls, want 1", stub.calls)
	}

	// Nothing has changed, so a second pass judges nothing at all.
	enrichAll(t, srv)
	if stub.calls != 1 {
		t.Fatalf("second pass re-judged; calls = %d, want 1", stub.calls)
	}

	// Re-titling a req in place must invalidate its verdict: the stored level
	// describes a title that no longer exists.
	if _, err := srv.store.pool.Exec(context.Background(),
		`UPDATE jobs SET title = 'Senior Frontend Engineer' WHERE company = 'Acme' AND job_id = '2'`,
	); err != nil {
		t.Fatalf("retitle: %v", err)
	}
	enrichAll(t, srv)
	if stub.calls != 2 {
		t.Fatalf("re-titled job was not re-judged; calls = %d, want 2", stub.calls)
	}

	var level string
	if err := srv.store.pool.QueryRow(context.Background(),
		`SELECT level FROM job_enrichment WHERE company = 'Acme' AND job_id = '2'`,
	).Scan(&level); err != nil {
		t.Fatalf("read level: %v", err)
	}
	if level != LevelSenior {
		t.Fatalf("level after retitle = %q, want %q", level, LevelSenior)
	}
}

// The title-hash must be computed identically in Go and in SQL, or every job
// looks stale on every pass and the enricher re-judges the whole corpus nightly.
func TestTitleHashMatchesSQL(t *testing.T) {
	srv := setup(t)
	loc := "Remote - US"
	j := Job{Company: "Acme", Title: "Staff Software Engineer, Payments", Location: &loc}

	var fromSQL string
	if err := srv.store.pool.QueryRow(context.Background(),
		`SELECT `+strings.Replace(titleHashSQL, "j.", "", -1)+` FROM (SELECT $2::text AS title, $3::text AS location) j`,
		enrichModel, j.Title, loc,
	).Scan(&fromSQL); err != nil {
		t.Fatalf("sql hash: %v", err)
	}
	if got := titleHash(j); got != fromSQL {
		t.Fatalf("titleHash = %q but SQL computed %q", got, fromSQL)
	}
}

func TestUnknownLevelReachesEveryoneRegardlessOfFilter(t *testing.T) {
	srv := setup(t)
	enrichAll(t, srv)

	// Acme "2" Frontend Engineer is the only non-seed fixture row, and its title
	// carries no level — so it must arrive even for someone who asked only for
	// intern roles.
	sub := Subscriber{
		ID:          "",
		Preferences: Preferences{Levels: []string{LevelIntern}, USOnly: true},
	}
	jobs, err := srv.store.NewPostingsFor(context.Background(), sub, epoch(), 50)
	if err != nil {
		t.Fatalf("select: %v", err)
	}
	if len(jobs) != 1 || jobs[0].JobID != "2" {
		t.Fatalf("unlevelled posting was filtered out: %+v", jobs)
	}
}

func TestLevelFilterExcludesNamedLevels(t *testing.T) {
	srv := setup(t)
	ctx := context.Background()
	if _, err := srv.store.pool.Exec(ctx, `
		INSERT INTO jobs (company, job_id, title, url, first_seen_at, last_seen_at, is_seed) VALUES
			('Acme','5','Senior Software Engineer','https://acme.example/5','2026-08-03',now(),false),
			('Acme','6','Software Engineer Intern','https://acme.example/6','2026-08-03',now(),false)`,
	); err != nil {
		t.Fatalf("insert: %v", err)
	}
	enrichAll(t, srv)

	sub := Subscriber{Preferences: Preferences{Levels: []string{LevelIntern}, USOnly: true}}
	jobs, err := srv.store.NewPostingsFor(ctx, sub, epoch(), 50)
	if err != nil {
		t.Fatalf("select: %v", err)
	}
	got := map[string]bool{}
	for _, j := range jobs {
		got[j.JobID] = true
	}
	if !got["6"] {
		t.Fatal("intern role missing for a subscriber who asked for interns")
	}
	if !got["2"] {
		t.Fatal("unlevelled role missing; unknown must always be delivered")
	}
	if got["5"] {
		t.Fatal("senior role delivered to an intern-only subscriber")
	}
}
