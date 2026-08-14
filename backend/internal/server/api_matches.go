package server

import (
	"errors"
	"log"
	"net/http"
	"strconv"
	"time"
)

func (s *Server) handleRunMatch(w http.ResponseWriter, r *http.Request) {
	id, ok := userIDParam(w, r)
	if !ok {
		return
	}
	result, err := s.runMatch(r.Context(), id)
	switch {
	case errors.Is(err, ErrNotFound):
		writeError(w, http.StatusNotFound, "no such user")
	case errors.Is(err, ErrNoProfile):
		writeError(w, http.StatusBadRequest, "set a profile before matching")
	case err != nil:
		log.Printf("run match: %v", err)
		writeError(w, http.StatusInternalServerError, "could not run matching")
	default:
		writeJSON(w, http.StatusOK, result)
	}
}

func (s *Server) handleGetMatches(w http.ResponseWriter, r *http.Request) {
	id, ok := userIDParam(w, r)
	if !ok {
		return
	}

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

	matches, err := s.store.Matches(r.Context(), id, since, limit)
	if err != nil {
		log.Printf("get matches: %v", err)
		writeError(w, http.StatusInternalServerError, "could not list matches")
		return
	}
	writeJSON(w, http.StatusOK, matches)
}
