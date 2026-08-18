package server

import (
	"log"
	"net/http"
	"strconv"
	"time"
)

const (
	// feedPerCompany caps how many of one company appear, so a busy employer —
	// Microsoft routinely posts a dozen near-identical reqs in one run — cannot
	// fill the page on its own.
	feedPerCompany = 6
)

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

	jobs, err := s.store.SoftwareFeed(r.Context(), since, feedPerCompany, limit)
	if err != nil {
		log.Printf("feed: %v", err)
		writeError(w, http.StatusInternalServerError, "could not load the feed")
		return
	}
	writeJSON(w, http.StatusOK, decorate(jobs))
}

// handleStats serves the landing page's headline numbers.
func (s *Server) handleStats(w http.ResponseWriter, r *http.Request) {
	stats, err := s.store.Stats(r.Context(), time.Now().Add(-24*time.Hour))
	if err != nil {
		log.Printf("stats: %v", err)
		writeError(w, http.StatusInternalServerError, "could not load stats")
		return
	}
	writeJSON(w, http.StatusOK, stats)
}
