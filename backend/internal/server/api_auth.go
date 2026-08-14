package server

import (
	"context"
	"errors"
	"log"
	"net/http"
	"strings"
	"time"
)

type ctxKey int

const userIDKey ctxKey = 0

// handleAuthRequest starts a login: it finds or creates the account for an email,
// mints a single-use login token, and emails the link. It always answers 200 so
// the response never reveals whether an address is registered. In dev mode the
// link is returned in the body so the flow can be driven without an inbox.
func (s *Server) handleAuthRequest(w http.ResponseWriter, r *http.Request) {
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
		log.Printf("auth request (upsert): %v", err)
		writeError(w, http.StatusInternalServerError, "could not start login")
		return
	}
	raw, hash := newToken()
	if err := s.store.CreateLoginToken(r.Context(), user.ID, hash, time.Now().Add(loginTokenTTL)); err != nil {
		log.Printf("auth request (token): %v", err)
		writeError(w, http.StatusInternalServerError, "could not start login")
		return
	}
	link := s.appBaseURL + "/verify?token=" + raw
	if err := s.mailer.SendLoginLink(r.Context(), user.Email, link); err != nil {
		log.Printf("auth request (mail): %v", err)
		writeError(w, http.StatusInternalServerError, "could not send login email")
		return
	}

	resp := map[string]any{"ok": true}
	if s.devAuth {
		resp["dev_link"] = link
	}
	writeJSON(w, http.StatusOK, resp)
}

// handleAuthVerify spends a login token and issues a session. The session token
// is returned once, in the body; only its hash is stored.
func (s *Server) handleAuthVerify(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Token string `json:"token"`
	}
	if !decodeJSON(w, r, &body) {
		return
	}
	userID, err := s.store.ConsumeLoginToken(r.Context(), hashToken(body.Token))
	if errors.Is(err, ErrInvalidToken) {
		writeError(w, http.StatusUnauthorized, "this login link is invalid or has expired")
		return
	}
	if err != nil {
		log.Printf("auth verify (consume): %v", err)
		writeError(w, http.StatusInternalServerError, "could not verify login")
		return
	}

	raw, hash := newToken()
	if err := s.store.CreateSession(r.Context(), userID, hash, time.Now().Add(sessionTTL)); err != nil {
		log.Printf("auth verify (session): %v", err)
		writeError(w, http.StatusInternalServerError, "could not start session")
		return
	}
	view, err := s.store.UserView(r.Context(), userID)
	if err != nil {
		log.Printf("auth verify (view): %v", err)
		writeError(w, http.StatusInternalServerError, "could not load account")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"token": raw, "user": view})
}

func (s *Server) handleLogout(w http.ResponseWriter, r *http.Request) {
	if raw := bearerToken(r); raw != "" {
		if err := s.store.DeleteSession(r.Context(), hashToken(raw)); err != nil {
			log.Printf("logout: %v", err)
		}
	}
	w.WriteHeader(http.StatusNoContent)
}

// authed wraps a handler so it runs only with a valid session, injecting the
// resolved user id into the request context.
func (s *Server) authed(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		raw := bearerToken(r)
		if raw == "" {
			writeError(w, http.StatusUnauthorized, "authentication required")
			return
		}
		userID, err := s.store.UserBySession(r.Context(), hashToken(raw))
		if errors.Is(err, ErrNotFound) {
			writeError(w, http.StatusUnauthorized, "session expired; sign in again")
			return
		}
		if err != nil {
			log.Printf("auth middleware: %v", err)
			writeError(w, http.StatusInternalServerError, "could not verify session")
			return
		}
		next(w, r.WithContext(context.WithValue(r.Context(), userIDKey, userID)))
	}
}

// currentUser returns the authenticated user id set by authed.
func currentUser(r *http.Request) string {
	id, _ := r.Context().Value(userIDKey).(string)
	return id
}

func bearerToken(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if after, ok := strings.CutPrefix(h, "Bearer "); ok {
		return strings.TrimSpace(after)
	}
	return ""
}
