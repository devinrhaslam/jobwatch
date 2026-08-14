package server

import (
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strings"
)

// These handlers all run behind the authed middleware, so the account is the one
// resolved from the session (currentUser), never a path parameter — a user can
// only ever read or change their own data.

func (s *Server) handleGetMe(w http.ResponseWriter, r *http.Request) {
	view, err := s.store.UserView(r.Context(), currentUser(r))
	if errors.Is(err, ErrNotFound) {
		writeError(w, http.StatusNotFound, "no such user")
		return
	}
	if err != nil {
		log.Printf("get me: %v", err)
		writeError(w, http.StatusInternalServerError, "could not load account")
		return
	}
	writeJSON(w, http.StatusOK, view)
}

func (s *Server) handleSetProfile(w http.ResponseWriter, r *http.Request) {
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
	if err := s.store.SetProfile(r.Context(), currentUser(r), body.Profile); err != nil {
		log.Printf("set profile: %v", err)
		writeError(w, http.StatusInternalServerError, "could not save profile")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) handleSetWatchlist(w http.ResponseWriter, r *http.Request) {
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
	if err := s.store.SetWatchlist(r.Context(), currentUser(r), body.Companies); err != nil {
		log.Printf("set watchlist: %v", err)
		writeError(w, http.StatusInternalServerError, "could not save watchlist")
		return
	}
	w.WriteHeader(http.StatusNoContent)
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
