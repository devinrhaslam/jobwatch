package server

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
)

// fitModel and fitInstructions are the model and prompt the classifier actually
// sends — ported from jobwatch/filters.py. They double as the verdict-cache's
// fingerprint inputs (see profileHash), so editing either invalidates cached
// verdicts, exactly as prompt_fingerprint() does in Python. {profile} is
// substituted with the user's profile at call time.
const fitModel = "claude-opus-5"

const fitInstructions = `You are screening newly posted job listings for the candidate described below.

<candidate>
{profile}
</candidate>

For each listing, decide whether the candidate should see it in their daily
alert digest. Return relevant=true only when the role is a general backend or
full-stack software engineering IC role at roughly the senior or staff level.

Judge the actual job, not the wording. Companies name the same job differently
("Software Engineer", "Member of Technical Staff", "Staff Engineer", "Backend
Engineer"), and a team name after a comma usually describes which product the
role sits on rather than changing the discipline. Use what you know about the
company and the product area named in the title.

Mark relevant=false for specialised tracks the candidate is not targeting
(dedicated infrastructure/platform/SRE, data engineering, data science,
ML/research engineering, native mobile development for iOS or Android,
frontend/UI, security), for management or non-engineering roles, and for levels
well outside the band (internships, new grad, principal and above). An
unleveled title such as plain "Software Engineer" is fine — many companies do
not put a level in the title.

When a title names an engineering discipline, that name is decisive. "Software
Engineer - Android", "Staff Software Engineer (Frontend)", "Software Developer,
iOS, <product>" and "SDET, Payments" are all outside the target however senior
the level or however general the rest of the title reads. This is the limit of
the "a team name after a comma is the product area" guidance above: a product
area is what the code serves, a discipline is what the code is, and only the
latter decides. Judge a discipline the list does not name — games, graphics,
test automation, developer relations — the same way, against what the candidate
is targeting rather than against the list.

Also mark relevant=false when the role is clearly based outside the United
States — a listing in Bengaluru, Tokyo, London, or Sydney is not workable for
this candidate no matter how well the role itself fits. A role listing several
sites counts as relevant if any one of them is in the US. Treat unqualified
"Remote" or "Distributed" as relevant, since it usually includes the US, but
treat a region-qualified remote such as "Remote India" or "Remote - EMEA" as
outside it. When a listing carries no location at all, do not drop it on
location grounds — judge it on the role alone.

There is no manual review step: anything you mark relevant=false disappears
without the candidate ever seeing it. When a listing is genuinely borderline,
prefer relevant=true. That tiebreaker covers uncertainty about level, location,
or how broad the role is. It does not cover discipline: a title naming a
discipline outside the target is not borderline, however senior or appealing
the rest of it reads.

Give a reason of at most 10 words for every listing. Return one verdict per
listing, using the index shown. Respond with ONLY a JSON object of the form
{"verdicts":[{"index":<int>,"relevant":<bool>,"reason":<string>}]} and no other
text.`

// Verdict is one role-fit judgment.
type Verdict struct {
	Keep   bool
	Reason string
}

// Classifier decides whether jobs fit a candidate profile. The Claude-backed
// implementation is injected at construction; tests inject a stub, so the
// matching logic is exercised without the network — the same seam filters.py
// uses in Python.
type Classifier interface {
	Classify(ctx context.Context, profile string, jobs []Job) ([]Verdict, error)
}

// profileHash identifies the prompt that produced a cached verdict. It folds in
// the model and instructions alongside the profile so editing any of them
// discards verdicts judged under the old criteria.
func profileHash(profile string) string {
	sum := sha256.Sum256([]byte(fitModel + "\n" + profile + "\n" + fitInstructions))
	return hex.EncodeToString(sum[:])[:16]
}

type verdictKey struct {
	company, title, location string
}

func keyFor(j Job) verdictKey {
	loc := ""
	if j.Location != nil {
		loc = *j.Location
	}
	return verdictKey{company: j.Company, title: j.Title, location: loc}
}

// MatchResult is the summary a match run returns.
type MatchResult struct {
	Evaluated int `json:"evaluated"`
	Kept      int `json:"kept"`
}

// runMatch evaluates a user's new watchlist jobs against their profile and
// stages the keepers. It is the per-user pass: candidates are jobs first seen
// since the user's cursor (bounded per company by when they added it), verdicts
// are cached so the classifier is only asked about titles it hasn't judged for
// this profile, and only genuine keepers are written to matches.
func (s *Server) runMatch(ctx context.Context, userID string) (MatchResult, error) {
	profile, err := s.store.Profile(ctx, userID)
	if err != nil {
		return MatchResult{}, err
	}

	cursor, err := s.store.LastMatchedAt(ctx, userID)
	if err != nil {
		return MatchResult{}, err
	}
	candidates, err := s.store.CandidateJobs(ctx, userID, cursor)
	if err != nil {
		return MatchResult{}, err
	}

	hash := profileHash(profile)

	// Everything the classifier has already judged for this profile.
	cached, err := s.store.FitVerdicts(ctx, hash, candidates)
	if err != nil {
		return MatchResult{}, err
	}

	// The distinct titles not yet judged — one classification each, not one per
	// duplicate posting.
	var pending []Job
	seen := map[verdictKey]bool{}
	for _, job := range candidates {
		key := keyFor(job)
		if _, ok := cached[key]; ok || seen[key] {
			continue
		}
		seen[key] = true
		pending = append(pending, job)
	}

	if len(pending) > 0 {
		verdicts, err := s.classifier.Classify(ctx, profile, pending)
		if err != nil {
			return MatchResult{}, err
		}
		if err := s.store.SaveFitVerdicts(ctx, hash, pending, verdicts); err != nil {
			return MatchResult{}, err
		}
		for i, job := range pending {
			cached[keyFor(job)] = verdicts[i]
		}
	}

	kept := 0
	for _, job := range candidates {
		if verdict := cached[keyFor(job)]; verdict.Keep {
			if err := s.store.StageMatch(ctx, userID, job, verdict.Reason); err != nil {
				return MatchResult{}, err
			}
			kept++
		}
	}

	// Advance the cursor last: a job first seen before now has now been
	// considered, so the next run starts after this point.
	if err := s.store.SetLastMatchedAt(ctx, userID); err != nil {
		return MatchResult{}, err
	}
	return MatchResult{Evaluated: len(candidates), Kept: kept}, nil
}
