package server

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"strconv"
	"time"
)

const (
	defaultJobsLimit = 100
	maxJobsLimit     = 1000
)

// Server holds the read store and turns it into HTTP handlers.
type Server struct {
	store *Store
}

// New connects the store. The caller must Close it.
func New(ctx context.Context, dsn string) (*Server, error) {
	store, err := newStore(ctx, dsn)
	if err != nil {
		return nil, err
	}
	return &Server{store: store}, nil
}

func (s *Server) Close() { s.store.Close() }

// Routes wires the read API. Method-qualified patterns need Go 1.22+.
func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /companies", s.handleCompanies)
	mux.HandleFunc("GET /jobs", s.handleJobs)
	mux.HandleFunc("GET /health", s.handleHealth)
	return mux
}

func (s *Server) handleCompanies(w http.ResponseWriter, r *http.Request) {
	companies, err := s.store.Companies(r.Context())
	if err != nil {
		log.Printf("companies: %v", err)
		writeError(w, http.StatusInternalServerError, "could not list companies")
		return
	}
	writeJSON(w, http.StatusOK, companies)
}

func (s *Server) handleJobs(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	company := q.Get("company")

	since := time.Unix(0, 0).UTC()
	if raw := q.Get("since"); raw != "" {
		parsed, err := time.Parse(time.RFC3339, raw)
		if err != nil {
			writeError(w, http.StatusBadRequest, "since must be RFC3339, e.g. 2026-08-13T00:00:00Z")
			return
		}
		since = parsed
	}

	limit := defaultJobsLimit
	if raw := q.Get("limit"); raw != "" {
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

	jobs, err := s.store.Jobs(r.Context(), company, since, limit)
	if err != nil {
		log.Printf("jobs: %v", err)
		writeError(w, http.StatusInternalServerError, "could not list jobs")
		return
	}
	writeJSON(w, http.StatusOK, jobs)
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	health, err := s.store.Health(r.Context())
	if err != nil {
		log.Printf("health: %v", err)
		writeError(w, http.StatusServiceUnavailable, "database unreachable")
		return
	}
	writeJSON(w, http.StatusOK, health)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("encode: %v", err)
	}
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
