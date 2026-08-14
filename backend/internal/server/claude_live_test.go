package server

import (
	"context"
	"os"
	"testing"
)

// A live test of the real Claude classifier, gated on ANTHROPIC_API_KEY so it is
// skipped by default (and never runs in the DB-gated suite unless a key is set).
// It classifies a tiny hand-picked batch — a couple of clear fits and a few
// clear non-fits — so it costs one API call and asserts the obvious verdicts.
func TestClaudeClassifierLive(t *testing.T) {
	if os.Getenv("ANTHROPIC_API_KEY") == "" {
		t.Skip("set ANTHROPIC_API_KEY to run the live classifier test")
	}

	loc := func(s string) *string { return &s }
	jobs := []Job{
		{Company: "Stripe", JobID: "keep1", Title: "Software Engineer, Payments", Location: loc("San Francisco, CA")},
		{Company: "Stripe", JobID: "keep2", Title: "Staff Backend Engineer", Location: loc("Remote")},
		{Company: "Stripe", JobID: "drop1", Title: "Account Executive, Enterprise", Location: loc("New York, NY")},
		{Company: "Stripe", JobID: "drop2", Title: "Data Scientist, Risk", Location: loc("Seattle, WA")},
		{Company: "Stripe", JobID: "drop3", Title: "Software Engineer, Android", Location: loc("Remote")},
	}
	profile := "Senior backend/full-stack software engineer, ~8 years, Go/TypeScript/Python, US-remote."

	verdicts, err := newClaudeClassifier().Classify(context.Background(), profile, jobs)
	if err != nil {
		t.Fatalf("classify: %v", err)
	}
	if len(verdicts) != len(jobs) {
		t.Fatalf("got %d verdicts, want %d", len(verdicts), len(jobs))
	}

	want := map[string]bool{"keep1": true, "keep2": true, "drop1": false, "drop2": false, "drop3": false}
	for i, j := range jobs {
		if verdicts[i].Keep != want[j.JobID] {
			t.Errorf("%s (%q): keep=%v, want %v — reason %q",
				j.JobID, j.Title, verdicts[i].Keep, want[j.JobID], verdicts[i].Reason)
		} else {
			t.Logf("%s (%q): keep=%v — %q", j.JobID, j.Title, verdicts[i].Keep, verdicts[i].Reason)
		}
	}
}
