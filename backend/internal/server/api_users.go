package server

import (
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strings"

	"github.com/google/uuid"
)

// NOTE: these endpoints are not yet auth-protected — the account is named by the
// id in the path. Magic-link auth is the next slice, after which these become
// "me"-scoped. Until then this is a development foundation, not a public surface.

func (s *Server) handleCreateUser(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Email string `json:"email"`
	}
	if !decodeJSON(w, r, &body) {
		return
	}
	if !strings.Contains(body.Email, "@") {
		writeError(w, http.StatusBadRequest, "a valid email is required")
		return
	}
	user, err := s.store.UpsertUser(r.Context(), body.Email)
	if err != nil {
		log.Printf("create user: %v", err)
		writeError(w, http.StatusInternalServerError, "could not create user")
		return
	}
	writeJSON(w, http.StatusOK, user)
}

func (s *Server) handleGetUser(w http.ResponseWriter, r *http.Request) {
	id, ok := userIDParam(w, r)
	if !ok {
		return
	}
	view, err := s.store.UserView(r.Context(), id)
	if errors.Is(err, ErrNotFound) {
		writeError(w, http.StatusNotFound, "no such user")
		return
	}
	if err != nil {
		log.Printf("get user: %v", err)
		writeError(w, http.StatusInternalServerError, "could not load user")
		return
	}
	writeJSON(w, http.StatusOK, view)
}

func (s *Server) handleSetProfile(w http.ResponseWriter, r *http.Request) {
	id, ok := userIDParam(w, r)
	if !ok {
		return
	}
	var body struct {
		Profile string `json:"profile"`
	}
	if !decodeJSON(w, r, &body) {
		return
	}
	if strings.TrimSpace(body.Profile) == "" {
		writeError(w, http.StatusBadRequest, "profile must not be empty")
		return
	}
	err := s.store.SetProfile(r.Context(), id, body.Profile)
	if errors.Is(err, ErrNotFound) {
		writeError(w, http.StatusNotFound, "no such user")
		return
	}
	if err != nil {
		log.Printf("set profile: %v", err)
		writeError(w, http.StatusInternalServerError, "could not save profile")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) handleSetWatchlist(w http.ResponseWriter, r *http.Request) {
	id, ok := userIDParam(w, r)
	if !ok {
		return
	}
	var body struct {
		Companies []string `json:"companies"`
	}
	if !decodeJSON(w, r, &body) {
		return
	}
	unknown, err := s.store.UnknownCompanies(r.Context(), body.Companies)
	if err != nil {
		log.Printf("validate watchlist: %v", err)
		writeError(w, http.StatusInternalServerError, "could not validate companies")
		return
	}
	if len(unknown) > 0 {
		writeError(w, http.StatusBadRequest, "not tracked: "+strings.Join(unknown, ", "))
		return
	}
	err = s.store.SetWatchlist(r.Context(), id, body.Companies)
	if errors.Is(err, ErrNotFound) {
		writeError(w, http.StatusNotFound, "no such user")
		return
	}
	if err != nil {
		log.Printf("set watchlist: %v", err)
		writeError(w, http.StatusInternalServerError, "could not save watchlist")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// userIDParam reads and validates the {id} path segment as a UUID.
func userIDParam(w http.ResponseWriter, r *http.Request) (string, bool) {
	id := r.PathValue("id")
	if _, err := uuid.Parse(id); err != nil {
		writeError(w, http.StatusBadRequest, "invalid user id")
		return "", false
	}
	return id, true
}

// decodeJSON strictly decodes a request body, writing a 400 and returning false
// on malformed input or unexpected fields.
func decodeJSON(w http.ResponseWriter, r *http.Request, v any) bool {
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(v); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return false
	}
	return true
}
