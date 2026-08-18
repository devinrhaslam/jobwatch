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

// A live test of the enricher's role and location judgment, gated on
// ANTHROPIC_API_KEY like the fit test above. The cases are drawn from real
// listings observed in the deployed feed, because the location formats vary
// wildly across 267 scrapers and that variance — not the obvious "Bangalore"
// case — is what the prompt has to survive. Each case isolates one rule, so a
// failure names the rule that regressed.
//
// "Delivered" here is is_swe AND is_us, which is what both the public feed and a
// default subscriber's digest actually select on.
func TestClaudeEnricherRoleAndLocationLive(t *testing.T) {
	if os.Getenv("ANTHROPIC_API_KEY") == "" {
		t.Skip("set ANTHROPIC_API_KEY to run the live enricher test")
	}

	loc := func(s string) *string { return &s }
	cases := []struct {
		job  Job
		want bool
		rule string
	}{
		// US software engineering: the baseline keeps.
		{Job{Company: "Zscaler", JobID: "us1", Title: "Staff Software Development Engineer", Location: loc("San Jose, California, USA")}, true, "plain US site"},
		{Job{Company: "Workday", JobID: "us2", Title: "Senior Software Development Engineer", Location: loc("USA CO Boulder (+3 Locations)")}, true, "US site with +N suffix"},
		{Job{Company: "NVIDIA", JobID: "us3", Title: "Senior Software Engineer, Platforms", Location: loc("US CA Remote (+6 Locations)")}, true, "US remote with +N suffix"},

		// Multi-site listings count as US if any one site is US.
		{Job{Company: "Sentry", JobID: "multi1", Title: "Senior Software Engineer, Streaming Platform", Location: loc("San Francisco, California, Toronto, Ontario, Canada")}, true, "multi-site including US"},

		// Remote: unqualified keeps, region-qualified drops.
		{Job{Company: "Vanta", JobID: "rem1", Title: "Senior Software Engineer", Location: loc("Remote U.S.")}, true, "US-qualified remote"},
		{Job{Company: "Tailscale", JobID: "rem2", Title: "Software Engineer, Platform", Location: loc("Remote (United States)")}, true, "US-qualified remote, parenthesised"},
		{Job{Company: "Stripe", JobID: "rem3", Title: "Backend Engineer", Location: loc("Remote")}, true, "unqualified remote"},
		{Job{Company: "Twilio", JobID: "rem4", Title: "Senior Software Engineer", Location: loc("Remote - India")}, false, "region-qualified remote (India)"},
		{Job{Company: "Tailscale", JobID: "rem5", Title: "Software Engineer, Platform", Location: loc("Remote (Canada)")}, false, "region-qualified remote (Canada)"},

		// Missing or placeholder location must not be dropped on location grounds.
		{Job{Company: "Synopsys", JobID: "noloc1", Title: "Senior Software Engineer, Compilers", Location: nil}, true, "nil location judged on role alone"},
		{Job{Company: "Stripe", JobID: "noloc2", Title: "Software Engineer, Payments", Location: loc("N/A")}, true, "placeholder location judged on role alone"},

		// Clearly non-US sites, in the formats the scrapers actually emit.
		{Job{Company: "GitLab", JobID: "intl1", Title: "Senior Backend Engineer", Location: loc("Bangalore, India")}, false, "named non-US city"},
		{Job{Company: "NVIDIA", JobID: "intl2", Title: "Senior Software Engineer, Platforms", Location: loc("Israel, Tel Aviv")}, false, "country-first format"},
		{Job{Company: "Visa", JobID: "intl3", Title: "Senior Software Engineer", Location: loc("SG - Singapore")}, false, "country-code prefix format"},
		{Job{Company: "Workday", JobID: "intl4", Title: "Software Development Engineer", Location: loc("IND.Pune")}, false, "abbreviated country prefix"},
		{Job{Company: "SentinelOne", JobID: "intl5", Title: "Senior Software Engineer", Location: loc("Brno, South Moravian, Czech Republic")}, false, "country the prompt never names"},

		// Role filtering must still work — a US location does not rescue a non-SWE role.
		{Job{Company: "Brex", JobID: "role1", Title: "Senior Technical Recruiter", Location: loc("San Francisco, California, United States")}, false, "non-SWE role in the US"},
		{Job{Company: "Capital One", JobID: "role2", Title: "Risk Manager (US Card)", Location: loc("Richmond VA")}, false, "manager role in the US"},
	}

	jobs := make([]Job, len(cases))
	for i, c := range cases {
		jobs[i] = c.job
	}

	got, err := newClaudeClassifier().Enrich(context.Background(), jobs)
	if err != nil {
		t.Fatalf("enrich: %v", err)
	}
	if len(got) != len(jobs) {
		t.Fatalf("got %d verdicts, want %d", len(got), len(jobs))
	}

	for i, c := range cases {
		delivered := got[i].IsSWE && got[i].IsUS
		if delivered != c.want {
			t.Errorf("%s [%s]: %q at %s — delivered=%v (swe=%v us=%v), want %v (reason %q)",
				c.job.JobID, c.rule, c.job.Title, locString(c.job.Location),
				delivered, got[i].IsSWE, got[i].IsUS, c.want, got[i].Reason)
		}
	}
}

// A live test of the level vocabulary — the filter subscribers actually choose
// from. The important cases are the last group: a title that states no level
// must come back `unknown`, never a plausible guess, because an invented level
// silently hides the role from everyone who filtered.
func TestClaudeEnricherLevelsLive(t *testing.T) {
	if os.Getenv("ANTHROPIC_API_KEY") == "" {
		t.Skip("set ANTHROPIC_API_KEY to run the live enricher test")
	}

	loc := func(s string) *string { return &s }
	cases := []struct {
		job  Job
		want string
		rule string
	}{
		{Job{Company: "TikTok", JobID: "l1", Title: "Mobile Software Engineer Intern (Global E-Commerce) - 2027 Summer", Location: loc("San Jose, CA")}, LevelIntern, "explicit intern"},
		{Job{Company: "American Express", JobID: "l2", Title: "Campus Undergraduate Summer Internship Program - 2027 Software Engineer", Location: loc("New York, NY")}, LevelIntern, "campus internship phrasing"},
		{Job{Company: "Google", JobID: "l3", Title: "Software Engineer, University Graduate, 2027", Location: loc("Mountain View, CA")}, LevelNewGrad, "university graduate"},
		{Job{Company: "Acme", JobID: "l4", Title: "Software Engineer I", Location: loc("Austin, TX")}, LevelJunior, "ladder suffix I"},
		{Job{Company: "Walmart", JobID: "l5", Title: "(USA) Software Engineer III", Location: loc("Sunnyvale, CA")}, LevelMid, "ladder suffix III"},
		{Job{Company: "Microsoft", JobID: "l6", Title: "Sr. Software Engineer - Azure Storage", Location: loc("Redmond, WA")}, LevelSenior, "abbreviated senior"},
		{Job{Company: "Walmart", JobID: "l7", Title: "(USA) Staff, Software Engineer", Location: loc("Sunnyvale, CA")}, LevelStaff, "staff with odd comma placement"},

		// The cases that matter most: no level stated anywhere in the title.
		{Job{Company: "Google", JobID: "u1", Title: "Software Engineer, Ads", Location: loc("Mountain View, CA")}, LevelUnknown, "bare title with a team suffix"},
		{Job{Company: "Palantir", JobID: "u2", Title: "Forward Deployed Software Engineer", Location: loc("Denver, CO")}, LevelUnknown, "seniority-sounding but unlevelled"},
		{Job{Company: "eBay", JobID: "u3", Title: "AI Native MTS1 Software Engineer, Risk", Location: loc("San Jose, CA")}, LevelUnknown, "unmappable company ladder"},
	}

	jobs := make([]Job, len(cases))
	for i, c := range cases {
		jobs[i] = c.job
	}
	got, err := newClaudeClassifier().Enrich(context.Background(), jobs)
	if err != nil {
		t.Fatalf("enrich: %v", err)
	}
	for i, c := range cases {
		if got[i].Level != c.want {
			t.Errorf("%s [%s]: %q — level=%q, want %q (reason %q)",
				c.job.JobID, c.rule, c.job.Title, got[i].Level, c.want, got[i].Reason)
		}
	}
}

func locString(p *string) string {
	if p == nil {
		return "<nil>"
	}
	return *p
}
