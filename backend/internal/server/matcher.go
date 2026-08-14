package server

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
)

// fitModel and fitInstructions mirror jobwatch/filters.py. They exist here only
// to compute the profile hash the verdict cache is keyed on; the real prompt and
// Claude call live in the classifier implementation (a later slice). Keeping the
// hash inputs identical to what the classifier sends means editing either one
// invalidates the cache, exactly as prompt_fingerprint() does in Python.
const fitModel = "claude-opus-5"

const fitInstructions = `You are screening newly posted job listings for the candidate described below.
Return relevant=true only when the role is a general backend or full-stack
software engineering IC role at roughly the senior or staff level, workable from
the United States. Judge the actual job, not the wording. Mark relevant=false for
specialised tracks the candidate is not targeting (infrastructure/platform/SRE,
data engineering, data science, ML/research, native mobile, frontend/UI,
security), for management or non-engineering roles, for levels well outside the
band, and for roles clearly based outside the US. When genuinely borderline on
level, location, or breadth, prefer relevant=true; a title naming a discipline
outside the target is not borderline.`

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

// keepAllClassifier is the placeholder default: it keeps every job. It exists so
// the service compiles and the matcher runs end to end before the Claude-backed
// classifier is wired in; main.go logs a warning when it is in use. Not for
// production — it does no filtering.
type keepAllClassifier struct{}

func (keepAllClassifier) Classify(_ context.Context, _ string, jobs []Job) ([]Verdict, error) {
	out := make([]Verdict, len(jobs))
	for i := range jobs {
		out[i] = Verdict{Keep: true, Reason: "unfiltered (placeholder classifier)"}
	}
	return out, nil
}
