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
// if feedInstructions changes.
const softwareFeedHash = "software-feed-v1"

// feedClassifyCap bounds how many recent jobs the public feed classifies on a
// cache miss, keeping the first uncached load's latency in check.
const feedClassifyCap = 250

// softwareFeed returns recent software-engineering roles for the public home
// page: the newest jobs first seen since `since`, classified once against the
// generic SWE prompt (cached in fit_verdicts) and filtered to keeps. On a
// classification error it degrades to the unfiltered recent jobs rather than
// breaking the page.
func (s *Server) softwareFeed(ctx context.Context, since time.Time, limit int) ([]Job, error) {
	recent, err := s.store.Jobs(ctx, "", since, feedClassifyCap)
	if err != nil {
		return nil, err
	}
	if len(recent) == 0 {
		return []Job{}, nil
	}

	cached, err := s.store.FitVerdicts(ctx, softwareFeedHash, recent)
	if err != nil {
		return nil, err
	}

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

	if len(pending) > 0 {
		verdicts, err := s.classifier.ClassifySoftware(ctx, pending)
		if err != nil {
			log.Printf("feed classification failed, showing unfiltered: %v", err)
			return capJobs(recent, limit), nil
		}
		if err := s.store.SaveFitVerdicts(ctx, softwareFeedHash, pending, verdicts); err != nil {
			log.Printf("feed: caching verdicts failed: %v", err)
		}
		for i, j := range pending {
			cached[keyFor(j)] = verdicts[i]
		}
	}

	keeps := make([]Job, 0, limit)
	for _, j := range recent {
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
