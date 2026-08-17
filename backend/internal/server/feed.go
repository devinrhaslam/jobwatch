package server

import (
	"context"
	"log"
	"net/http"
	"strconv"
	"time"
)

// softwareFeedHash namespaces the "is this software engineering" verdicts inside
// fit_verdicts, separate from any user's personal-fit verdicts. Bump the suffix
// whenever feedInstructions changes so old verdicts are re-judged.
const softwareFeedHash = "software-feed-v2"

const (
	// feedFetchLimit is the recent window pulled before diversifying — wide
	// enough that capping per company still leaves plenty of jobs.
	feedFetchLimit = 1000
	// feedPerCompany caps how many of one company appear, so a freshly-seeded
	// company (hundreds of jobs all first-seen "now") can't flood the feed.
	feedPerCompany = 6
	// feedClassifyCap bounds how many diverse jobs the feed classifies/shows.
	feedClassifyCap = 300
)

// diverseRecent caps each company to perCompany jobs (keeping newest-first order)
// and returns at most max jobs, so no single company dominates the feed.
func diverseRecent(jobs []Job, perCompany, max int) []Job {
	counts := map[string]int{}
	out := make([]Job, 0, max)
	for _, j := range jobs {
		if counts[j.Company] >= perCompany {
			continue
		}
		counts[j.Company]++
		out = append(out, j)
		if len(out) >= max {
			break
		}
	}
	return out
}

// softwareFeed returns recent software-engineering roles for the public home
// page: genuinely-new postings (seeds excluded) since `since`, diversified so no
// one company dominates, classified against the SWE prompt (cached), and filtered
// to keeps. On a classification error it degrades to the diverse unfiltered set
// rather than breaking the page.
func (s *Server) softwareFeed(ctx context.Context, since time.Time, limit int) ([]Job, error) {
	recent, err := s.store.RecentPostings(ctx, since, feedFetchLimit)
	if err != nil {
		return nil, err
	}
	candidates := diverseRecent(recent, feedPerCompany, feedClassifyCap)
	if len(candidates) == 0 {
		return []Job{}, nil
	}

	cached, err := s.store.FitVerdicts(ctx, softwareFeedHash, candidates)
	if err != nil {
		return nil, err
	}

	// In steady state ClassifyFeed (run by the cron) has already warmed the
	// cache, so pending is empty and nothing is classified in this request path.
	// This on-demand classification is only a fallback — before the first cron,
	// or for jobs newer than the last one.
	pending := pendingFeedJobs(candidates, cached)
	if len(pending) > 0 {
		verdicts, err := s.classifier.ClassifySoftware(ctx, pending)
		if err != nil {
			log.Printf("feed classification failed, showing unfiltered: %v", err)
			return capJobs(candidates, limit), nil
		}
		if err := s.store.SaveFitVerdicts(ctx, softwareFeedHash, pending, verdicts); err != nil {
			log.Printf("feed: caching verdicts failed: %v", err)
		}
		for i, j := range pending {
			cached[keyFor(j)] = verdicts[i]
		}
	}

	keeps := make([]Job, 0, limit)
	for _, j := range candidates {
		if cached[keyFor(j)].Keep {
			keeps = append(keeps, j)
			if len(keeps) >= limit {
				break
			}
		}
	}
	return keeps, nil
}

func capJobs(jobs []Job, limit int) []Job {
	if len(jobs) > limit {
		return jobs[:limit]
	}
	return jobs
}

// pendingFeedJobs is the subset of recent jobs with no cached feed verdict yet,
// deduplicated by verdict key.
func pendingFeedJobs(recent []Job, cached map[verdictKey]Verdict) []Job {
	var pending []Job
	seen := map[verdictKey]bool{}
	for _, j := range recent {
		k := keyFor(j)
		if _, ok := cached[k]; ok || seen[k] {
			continue
		}
		seen[k] = true
		pending = append(pending, j)
	}
	return pending
}

// ClassifyFeed pre-classifies recent jobs against the SWE prompt and caches the
// verdicts, so /feed serves from cache instead of classifying in the request
// path. Meant to run on a schedule after ingestion; returns how many it newly
// classified.
func (s *Server) ClassifyFeed(ctx context.Context, since time.Time) (int, error) {
	recent, err := s.store.RecentPostings(ctx, since, feedFetchLimit)
	if err != nil {
		return 0, err
	}
	candidates := diverseRecent(recent, feedPerCompany, feedClassifyCap)
	cached, err := s.store.FitVerdicts(ctx, softwareFeedHash, candidates)
	if err != nil {
		return 0, err
	}
	pending := pendingFeedJobs(candidates, cached)
	if len(pending) == 0 {
		return 0, nil
	}
	verdicts, err := s.classifier.ClassifySoftware(ctx, pending)
	if err != nil {
		return 0, err
	}
	if err := s.store.SaveFitVerdicts(ctx, softwareFeedHash, pending, verdicts); err != nil {
		return 0, err
	}
	return len(pending), nil
}

func (s *Server) handleFeed(w http.ResponseWriter, r *http.Request) {
	since := time.Unix(0, 0).UTC()
	if raw := r.URL.Query().Get("since"); raw != "" {
		parsed, err := time.Parse(time.RFC3339, raw)
		if err != nil {
			writeError(w, http.StatusBadRequest, "since must be RFC3339, e.g. 2026-08-13T00:00:00Z")
			return
		}
		since = parsed
	}

	limit := defaultJobsLimit
	if raw := r.URL.Query().Get("limit"); raw != "" {
		parsed, err := strconv.Atoi(raw)
		if err != nil || parsed < 1 {
			writeError(w, http.StatusBadRequest, "limit must be a positive integer")
			return
		}
		limit = parsed
	}
	if limit > maxJobsLimit {
		limit = maxJobsLimit
	}

	jobs, err := s.softwareFeed(r.Context(), since, limit)
	if err != nil {
		log.Printf("feed: %v", err)
		writeError(w, http.StatusInternalServerError, "could not load the feed")
		return
	}
	writeJSON(w, http.StatusOK, jobs)
}
