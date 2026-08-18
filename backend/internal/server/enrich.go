package server

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/anthropics/anthropic-sdk-go"
	"github.com/jackc/pgx/v5"
)

// Levels a listing can be assigned. `LevelUnknown` is the honest answer for the
// ~a third of real software titles that carry no level at all — "Software
// Engineer, Ads", "Distributed Software Engineer", "Senior SDE, Last Mile
// Delivery" is levelled but "Software Engineer, Identity" is not. Those rows are
// delivered to everyone regardless of their level filter; see LevelFilterSQL.
const (
	LevelIntern   = "intern"
	LevelNewGrad  = "new_grad"
	LevelJunior   = "junior"
	LevelMid      = "mid"
	LevelSenior   = "senior"
	LevelStaff    = "staff"
	LevelUnknown  = "unknown"
	enrichBatch   = 50
	enrichRetries = 2
)

// ValidLevels is the set a subscriber may filter on. `unknown` is deliberately
// absent: it is not something anyone opts into, it is what always comes through.
var ValidLevels = []string{LevelIntern, LevelNewGrad, LevelJunior, LevelMid, LevelSenior, LevelStaff}

func isValidLevel(s string) bool {
	for _, l := range ValidLevels {
		if l == s {
			return true
		}
	}
	return false
}

// enrichModel is the cheap, fast model for the structured pass. The question is
// mechanical — read a title, name a level — and runs over every new posting, so
// it does not warrant the top model.
const enrichModel = "claude-haiku-4-5-20251001"
const enrichMaxTokens = 8192

// enrichInstructions asks for role, level, and location in a single pass. It is
// one call rather than three because the model is reading the same short string
// either way, and because a title it judges non-software needs no level at all.
//
// The hard rule in here is the one about guessing: this pipeline never opens the
// posting, so anything the title does not say is genuinely unknown, and the
// model is told to say so rather than infer from a company's conventions.
const enrichInstructions = `You are enriching job listings for a software-engineering job alert service.
For each listing you receive a title, a company, and sometimes a location. That
is all the evidence there is — you cannot open the posting. Judge only what the
listing itself says.

Return four fields per listing.

1. relevant (boolean) — is this a software engineering role, a job whose core
work is writing and building software?

true for software engineering of any specialty and level: software engineer,
backend, frontend, full-stack, mobile (iOS/Android), embedded or firmware,
systems, platform, infrastructure, SRE, DevOps, security engineer, and
machine-learning or data ENGINEERS. Include internships, new grad, and
staff/principal.

false for everything else, including technical or adjacent roles that are not
software engineering:
- data scientists, machine-learning / AI / applied / research SCIENTISTS,
  quantitative researchers, data analysts, analytics roles
- product, program, or project management, and engineering management
- design (UX/UI/graphic), sales, marketing, recruiting, HR, finance, legal,
  customer success, IT support, operations, warehouse and retail roles
- non-software engineering: mechanical, electrical, hardware, manufacturing,
  civil, and ERP/SAP functional roles

The distinction that matters: an engineer who builds software is in; a
scientist, researcher, analyst, manager, or non-software engineer is out — even
if the title contains "Engineer" or the role is technical.

2. level (string) — one of: intern, new_grad, junior, mid, senior, staff,
unknown.

  intern   — "Intern", "Internship", "Co-op", "Summer 2027", "Campus
             Undergraduate", any student placement.
  new_grad — "New Grad", "University Graduate", "Early Career", "Campus
             Graduate", "Rotational", explicitly aimed at graduating students.
  junior   — "Junior", "Jr", "Associate", "Entry Level", "I" as a ladder suffix
             ("Software Engineer I").
  mid      — "II", "III", "2", "3", "Mid-level", and company ladders that
             clearly denote a second or third rung.
  senior   — "Senior", "Sr", "Snr", "Lead" used as a seniority marker.
  staff    — "Staff", "Principal", "Distinguished", "Fellow", "Architect", and
             anything above senior.
  unknown  — THE TITLE DOES NOT SAY. This is a normal, frequent answer and is
             always better than a guess.

Use unknown for a bare "Software Engineer", "Software Engineer, Ads",
"Backend Engineer", "Forward Deployed Software Engineer". Do not infer a level
from the company, the team, the specialty, or how senior the work sounds. Only
the words in the title decide. A company-specific ladder you cannot map with
confidence (an "MTS1", an "E5", a "Level 60") is unknown, not a guess.

3. us (boolean) — is this role based in the United States?

true when a named location is in the US, and true when several sites are listed
and any one of them is in the US. Treat unqualified "Remote" or "Distributed" as
true, since it usually includes the US. Treat a region-qualified remote such as
"Remote - India" or "Remote - EMEA" as false. A listing in Bengaluru, Tokyo,
London, or Dublin is false. Judge a country the examples do not name the same
way — against whether the role is in the US. When a listing carries no location
at all, or only a placeholder such as "N/A" or "-", return true: absent evidence
must not silently hide a role.

4. remote (boolean) — does the location say the role is remote? true only when
the listing actually says so ("Remote", "US Remote", "Distributed", "Work from
home"). A named office is false. Absent a location, false.

Give a reason of at most 8 words.
Return one verdict per listing using the index shown, as JSON:
{"verdicts":[{"index":<int>,"relevant":<bool>,"level":<string>,"us":<bool>,"remote":<bool>,"reason":<string>}]}
and nothing else.`

// Enrichment is the structured verdict for one listing: everything a subscriber
// can filter on, derived from the title and location alone.
type Enrichment struct {
	IsSWE    bool
	Level    string
	IsUS     bool
	IsRemote bool
	Reason   string
}

// Enricher produces structured facts for listings. Split from Classifier so the
// digest and feed paths depend only on this, and so tests can stub it without
// implementing the personal-fit classifier too.
type Enricher interface {
	Enrich(ctx context.Context, jobs []Job) ([]Enrichment, error)
}

// Enrich judges a batch of listings for role, level, and location. Batches of 50
// bound any single request; a batch that comes back missing a listing is re-asked
// for just the gaps, matching classifyBatch's contract.
func (c *claudeClassifier) Enrich(ctx context.Context, jobs []Job) ([]Enrichment, error) {
	out := make([]Enrichment, 0, len(jobs))
	for start := 0; start < len(jobs); start += enrichBatch {
		end := min(start+enrichBatch, len(jobs))
		got, err := c.enrichBatch(ctx, jobs[start:end], 0)
		if err != nil {
			return nil, err
		}
		out = append(out, got...)
	}
	return out, nil
}

func (c *claudeClassifier) enrichBatch(ctx context.Context, jobs []Job, attempt int) ([]Enrichment, error) {
	var listings strings.Builder
	for i, j := range jobs {
		loc := ""
		if j.Location != nil && *j.Location != "" {
			loc = " (" + *j.Location + ")"
		}
		fmt.Fprintf(&listings, "%d. %s — %s%s\n", i, j.Title, j.Company, loc)
	}

	msg, err := c.client.Messages.New(ctx, anthropic.MessageNewParams{
		Model:     anthropic.Model(enrichModel),
		MaxTokens: int64(enrichMaxTokens),
		System:    []anthropic.TextBlockParam{{Text: enrichInstructions}},
		Messages: []anthropic.MessageParam{
			anthropic.NewUserMessage(anthropic.NewTextBlock(listings.String())),
		},
	})
	if err != nil {
		return nil, fmt.Errorf("enrichment request failed: %w", err)
	}

	var text strings.Builder
	for _, block := range msg.Content {
		if block.Type == "text" {
			text.WriteString(block.Text)
		}
	}

	var parsed struct {
		Verdicts []struct {
			Index    int    `json:"index"`
			Relevant bool   `json:"relevant"`
			Level    string `json:"level"`
			US       bool   `json:"us"`
			Remote   bool   `json:"remote"`
			Reason   string `json:"reason"`
		} `json:"verdicts"`
	}
	if err := json.Unmarshal([]byte(extractJSON(text.String())), &parsed); err != nil {
		return nil, fmt.Errorf("could not parse enrichment response: %w", err)
	}

	byIndex := make(map[int]Enrichment, len(parsed.Verdicts))
	for _, v := range parsed.Verdicts {
		level := strings.ToLower(strings.TrimSpace(v.Level))
		// A level outside the vocabulary is treated as unknown rather than
		// stored verbatim. An invented value would sit in the column filtering
		// nobody, which is a silent bug; `unknown` at least always delivers.
		if !isValidLevel(level) {
			level = LevelUnknown
		}
		byIndex[v.Index] = Enrichment{
			IsSWE:    v.Relevant,
			Level:    level,
			IsUS:     v.US,
			IsRemote: v.Remote,
			Reason:   v.Reason,
		}
	}

	var missing []int
	for i := range jobs {
		if _, ok := byIndex[i]; !ok {
			missing = append(missing, i)
		}
	}
	if len(missing) > 0 {
		if attempt >= enrichRetries {
			return nil, fmt.Errorf("enrichment omitted %d of %d listings after %d attempts",
				len(missing), len(jobs), attempt+1)
		}
		gaps := make([]Job, len(missing))
		for k, i := range missing {
			gaps[k] = jobs[i]
		}
		retried, err := c.enrichBatch(ctx, gaps, attempt+1)
		if err != nil {
			return nil, err
		}
		for k, i := range missing {
			byIndex[i] = retried[k]
		}
	}

	out := make([]Enrichment, len(jobs))
	for i := range jobs {
		out[i] = byIndex[i]
	}
	return out, nil
}

// titleHash fingerprints the evidence a verdict was judged from — the model plus
// the exact title and location it read — so a board that re-titles a req in place
// invalidates its enrichment instead of serving a level derived from a title that
// no longer exists.
//
// titleHashSQL below must produce byte-identical output for the same row; the two
// are asserted equal in TestTitleHashMatchesSQL.
func titleHash(j Job) string {
	loc := ""
	if j.Location != nil {
		loc = *j.Location
	}
	sum := sha256.Sum256([]byte(enrichModel + "\n" + j.Title + "\n" + loc))
	return hex.EncodeToString(sum[:])[:16]
}

// titleHashSQL is titleHash expressed over a `jobs` row, so "has this listing
// changed since we judged it" is answered by the database rather than by
// fetching every candidate and comparing in Go. $1 must be bound to enrichModel.
const titleHashSQL = `left(encode(sha256(convert_to(
	$1 || E'\n' || j.title || E'\n' || coalesce(j.location, ''), 'UTF8')), 'hex'), 16)`

// UnenrichedJobs returns genuinely-new postings since `since` that have no
// current enrichment — either never judged, or judged from a title that has
// since changed. Newest first, bounded by limit.
func (s *Store) UnenrichedJobs(ctx context.Context, since time.Time, limit int) ([]Job, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT j.company, j.job_id, j.title, j.url, j.location, j.posted_date,
		       j.first_seen_at, j.last_seen_at
		FROM jobs j
		LEFT JOIN job_enrichment e
		       ON e.company = j.company AND e.job_id = j.job_id
		WHERE NOT j.is_seed
		  AND j.first_seen_at > $2
		  AND (e.company IS NULL OR e.title_hash <> `+titleHashSQL+`)
		ORDER BY j.first_seen_at DESC, j.job_id
		LIMIT $3`, enrichModel, since, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanJobs(rows)
}

// SaveEnrichments upserts a batch of verdicts. Re-judging a listing overwrites
// the old row, which is what a title change should do.
func (s *Store) SaveEnrichments(ctx context.Context, jobs []Job, got []Enrichment) error {
	if len(jobs) != len(got) {
		return fmt.Errorf("saving enrichments: %d jobs but %d verdicts", len(jobs), len(got))
	}
	batch := &pgx.Batch{}
	for i, j := range jobs {
		e := got[i]
		batch.Queue(`
			INSERT INTO job_enrichment
			    (company, job_id, title_hash, is_swe, level, is_us, is_remote, reason, judged_at)
			VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
			ON CONFLICT (company, job_id) DO UPDATE SET
			    title_hash = EXCLUDED.title_hash,
			    is_swe     = EXCLUDED.is_swe,
			    level      = EXCLUDED.level,
			    is_us      = EXCLUDED.is_us,
			    is_remote  = EXCLUDED.is_remote,
			    reason     = EXCLUDED.reason,
			    judged_at  = now()`,
			j.Company, j.JobID, titleHash(j), e.IsSWE, e.Level, e.IsUS, e.IsRemote, e.Reason)
	}
	return s.pool.SendBatch(ctx, batch).Close()
}

// EnrichNew judges every unenriched posting since `since` and stores the
// verdicts, returning how many it judged. This is the cron's job: after it runs,
// both the feed and the digest are pure SQL with no model in the request path.
func (s *Server) EnrichNew(ctx context.Context, since time.Time, limit int) (int, error) {
	pending, err := s.store.UnenrichedJobs(ctx, since, limit)
	if err != nil {
		return 0, err
	}
	if len(pending) == 0 {
		return 0, nil
	}
	got, err := s.enricher.Enrich(ctx, pending)
	if err != nil {
		return 0, err
	}
	if err := s.store.SaveEnrichments(ctx, pending, got); err != nil {
		return 0, err
	}
	return len(pending), nil
}
