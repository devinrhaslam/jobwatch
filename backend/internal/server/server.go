package server

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"
)

const (
	defaultJobsLimit = 100
	maxJobsLimit     = 1000
)

// Server holds the read/write store, the fit classifier, the mailer, and the
// HTTP handlers.
type Server struct {
	store      *Store
	classifier Classifier
	mailer     Mailer
	appBaseURL string // where the magic link points (the frontend origin)
	devAuth    bool   // when true, /auth/request returns the link in its body
}

// New connects the store and wires the Claude-backed fit classifier and the dev
// mailer. The caller must Close it. Tests override the classifier and mailer
// fields with stubs so they never hit the network. Config from env:
// JOBWATCH_APP_URL (magic-link base, default http://localhost:5173) and
// JOBWATCH_DEV_AUTH (=1 to return the link in the response, for local dev).
func New(ctx context.Context, dsn string) (*Server, error) {
	store, err := newStore(ctx, dsn)
	if err != nil {
		return nil, err
	}
	appURL := os.Getenv("JOBWATCH_APP_URL")
	if appURL == "" {
		appURL = "http://localhost:5173"
	}
	return &Server{
		store:      store,
		classifier: newClaudeClassifier(),
		mailer:     logMailer{},
		appBaseURL: appURL,
		devAuth:    os.Getenv("JOBWATCH_DEV_AUTH") == "1",
	}, nil
}

func (s *Server) Close() { s.store.Close() }

// Routes wires the API. Method-qualified patterns need Go 1.22+. Public routes
// serve reference data and the login flow; /me routes require a session.
func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /companies", s.handleCompanies)
	mux.HandleFunc("GET /jobs", s.handleJobs)
	mux.HandleFunc("GET /health", s.handleHealth)

	mux.HandleFunc("POST /auth/request", s.handleAuthRequest)
	mux.HandleFunc("POST /auth/verify", s.handleAuthVerify)
	mux.HandleFunc("POST /auth/logout", s.handleLogout)

	mux.HandleFunc("GET /me", s.authed(s.handleGetMe))
	mux.HandleFunc("PUT /me/profile", s.authed(s.handleSetProfile))
	mux.HandleFunc("PUT /me/watchlist", s.authed(s.handleSetWatchlist))
	mux.HandleFunc("POST /me/match", s.authed(s.handleRunMatch))
	mux.HandleFunc("GET /me/matches", s.authed(s.handleGetMatches))
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
