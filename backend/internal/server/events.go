package server

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// The launch gates this instrumentation exists to answer:
//
//	reach       — signup_started
//	activation  — signup_confirmed / signup_started
//	value       — distinct users with job_clicked in their first 7 digests
//	retention   — users still opening/clicking in week 4
//	money       — later, when there is something to buy
//
// See metrics.sql for the queries. Opens are recorded but deliberately not a
// gate: Apple Mail Privacy Protection pre-fetches images, so a large and
// unknowable share of "opens" are a proxy server, not a person. Clicks are the
// signal.
const (
	EventSignupStarted   = "signup_started"
	EventSignupConfirmed = "signup_confirmed"
	EventPrefsChanged    = "prefs_changed"
	EventDigestSent      = "digest_sent"
	EventDigestOpened    = "digest_opened"
	EventJobClicked      = "job_clicked"
	EventUnsubscribed    = "unsubscribed"
	EventAccountDeleted  = "account_deleted"
)

// RecordEvent appends one analytics row. Analytics must never break a user's
// request, so a failure here is logged and swallowed — every caller ignores the
// return, and the signature returns nothing to make that the only option.
func (s *Store) RecordEvent(ctx context.Context, name string, userID *string, props map[string]any) {
	raw, err := json.Marshal(props)
	if err != nil {
		log.Printf("event %s: marshalling props: %v", name, err)
		raw = []byte("{}")
	}
	if _, err := s.pool.Exec(ctx,
		`INSERT INTO events (name, user_id, props) VALUES ($1, $2, $3)`,
		name, userID, raw,
	); err != nil {
		log.Printf("event %s: %v", name, err)
	}
}

// linkSecret keys the HMAC on tracked links. Without it the redirector would be
// an open redirect — anyone could hand out a link on our domain pointing
// anywhere — so when it is unset, tracking is disabled outright and emails carry
// plain destination links instead. Losing the click metric is a far smaller
// failure than shipping an open redirect.
func linkSecret() []byte {
	return []byte(os.Getenv("JOBWATCH_LINK_SECRET"))
}

func trackingEnabled() bool { return len(linkSecret()) > 0 }

func sign(payload string) string {
	mac := hmac.New(sha256.New, linkSecret())
	mac.Write([]byte(payload))
	return hex.EncodeToString(mac.Sum(nil))[:32]
}

func validSignature(payload, sig string) bool {
	return hmac.Equal([]byte(sign(payload)), []byte(sig))
}

// TrackedJobURL wraps a destination in a click-logging redirect. It returns the
// bare destination unchanged when tracking is disabled, so a missing secret
// degrades to an untracked — but working — link.
func (s *Server) TrackedJobURL(dest, company, jobID, userID string) string {
	if !trackingEnabled() || dest == "" {
		return dest
	}
	payload := base64.RawURLEncoding.EncodeToString([]byte(dest))
	q := url.Values{
		"u": {payload},
		"c": {company},
		"j": {jobID},
		"s": {sign(payload)},
	}
	if userID != "" {
		q.Set("i", userID)
	}
	return strings.TrimRight(s.apiBaseURL, "/") + "/e/c?" + q.Encode()
}

// handleClick logs a job click and forwards to the posting.
//
// The ordering here is the whole point: the redirect is issued whether or not
// the logging succeeded. A dead link is this project's recurring bug, and
// instrumentation must not become a new source of one — so a database outage
// costs a metric, never a user's click.
func (s *Server) handleClick(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	payload, sig := q.Get("u"), q.Get("s")
	if payload == "" || !validSignature(payload, sig) {
		writeError(w, http.StatusBadRequest, "invalid link")
		return
	}
	raw, err := base64.RawURLEncoding.DecodeString(payload)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid link")
		return
	}
	dest := string(raw)
	// The signature already proves we minted this link, so the destination is
	// ours; this only guards against a malformed one reaching a browser.
	if u, err := url.Parse(dest); err != nil || (u.Scheme != "http" && u.Scheme != "https") {
		writeError(w, http.StatusBadRequest, "invalid link")
		return
	}

	var userID *string
	if id := q.Get("i"); id != "" {
		userID = &id
	}
	s.store.RecordEvent(r.Context(), EventJobClicked, userID, map[string]any{
		"company": q.Get("c"),
		"job_id":  q.Get("j"),
	})

	http.Redirect(w, r, dest, http.StatusFound)
}

// a 1x1 transparent GIF, the smallest thing a mail client will fetch.
var pixelGIF = []byte{
	0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x01, 0x00, 0x01, 0x00, 0x80, 0x00, 0x00,
	0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x21, 0xf9, 0x04, 0x01, 0x00, 0x00, 0x00,
	0x2c, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x02, 0x02, 0x44,
	0x01, 0x00, 0x3b,
}

// OpenPixelURL is the tracking pixel for one user's digest, or "" if tracking is
// off (in which case the email simply omits the image).
func (s *Server) OpenPixelURL(userID string) string {
	if !trackingEnabled() || userID == "" {
		return ""
	}
	q := url.Values{"i": {userID}, "s": {sign(userID)}}
	return strings.TrimRight(s.apiBaseURL, "/") + "/e/o.gif?" + q.Encode()
}

// handleOpen records a digest open and always returns the pixel, valid signature
// or not — an image that 404s is visible to the reader as a broken box.
func (s *Server) handleOpen(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	if id := q.Get("i"); id != "" && validSignature(id, q.Get("s")) {
		s.store.RecordEvent(r.Context(), EventDigestOpened, &id, nil)
	}
	w.Header().Set("Content-Type", "image/gif")
	w.Header().Set("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
	w.Header().Set("Content-Length", "43")
	w.WriteHeader(http.StatusOK)
	if _, err := w.Write(pixelGIF); err != nil {
		log.Printf("open pixel: %v", err)
	}
}

// UnsubscribeURL is the one-click opt-out carried in every digest, both as a
// footer link and in the List-Unsubscribe header. It is signed rather than
// random so it needs no storage and never expires — a link in a year-old email
// must still work, because the alternative is a spam complaint.
func (s *Server) UnsubscribeURL(userID string) string {
	q := url.Values{"i": {userID}, "s": {sign("unsub:" + userID)}}
	return strings.TrimRight(s.apiBaseURL, "/") + "/u?" + q.Encode()
}

// handleUnsubscribe honours both the human click (GET) and the mail provider's
// automated POST from the List-Unsubscribe-Post header. Gmail and friends send
// the POST without any user interaction, so it must be side-effecting on its own
// and must not require a confirmation page.
func (s *Server) handleUnsubscribe(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	id := q.Get("i")
	if id == "" || !validSignature("unsub:"+id, q.Get("s")) {
		writeError(w, http.StatusBadRequest, "invalid unsubscribe link")
		return
	}
	if err := s.store.Unsubscribe(r.Context(), id); err != nil {
		log.Printf("unsubscribe: %v", err)
		writeError(w, http.StatusInternalServerError, "could not unsubscribe")
		return
	}
	s.store.RecordEvent(r.Context(), EventUnsubscribed, &id, nil)

	if r.Method == http.MethodPost {
		w.WriteHeader(http.StatusOK)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	if _, err := w.Write([]byte(unsubscribedPage(s.appBaseURL))); err != nil {
		log.Printf("unsubscribe page: %v", err)
	}
}

func unsubscribedPage(appURL string) string {
	return `<!doctype html><meta charset="utf-8">` +
		`<meta name="viewport" content="width=device-width,initial-scale=1">` +
		`<title>Unsubscribed</title>` +
		`<style>body{font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;` +
		`background:` + emailBg + `;color:` + emailInk + `;display:grid;place-items:center;` +
		`min-height:100vh;margin:0}` +
		`.c{background:` + emailCard + `;padding:40px;border-radius:14px;max-width:420px;` +
		`text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.06)}` +
		`a{color:` + emailAccent + `}</style>` +
		`<div class="c"><h1>You're unsubscribed</h1>` +
		`<p>You won't get any more job digests. No hard feelings.</p>` +
		`<p><a href="` + htmlAttr(appURL) + `">Change your mind?</a></p></div>`
}

// Unsubscribe stops all digests for an account without deleting it, so the
// address stays suppressed even if they sign in again later.
func (s *Store) Unsubscribe(ctx context.Context, userID string) error {
	_, err := s.pool.Exec(ctx,
		`UPDATE users SET unsubscribed_at = now() WHERE id = $1 AND unsubscribed_at IS NULL`,
		userID)
	return err
}

// Resubscribe clears the opt-out, for someone who changes their mind in the app.
func (s *Store) Resubscribe(ctx context.Context, userID string) error {
	_, err := s.pool.Exec(ctx,
		`UPDATE users SET unsubscribed_at = NULL WHERE id = $1`, userID)
	return err
}

// FunnelWindow is a coarse read of the launch gates, for the operator.
type FunnelWindow struct {
	Since             time.Time `json:"since"`
	SignupsStarted    int64     `json:"signups_started"`
	SignupsConfirmed  int64     `json:"signups_confirmed"`
	DigestsSent       int64     `json:"digests_sent"`
	UsersWhoClicked   int64     `json:"users_who_clicked"`
	Unsubscribes      int64     `json:"unsubscribes"`
	ConfirmedAccounts int64     `json:"confirmed_accounts"`
}

func (s *Store) Funnel(ctx context.Context, since time.Time) (FunnelWindow, error) {
	f := FunnelWindow{Since: since}
	err := s.pool.QueryRow(ctx, `
		SELECT
		  count(*) FILTER (WHERE name = $2),
		  count(*) FILTER (WHERE name = $3),
		  count(*) FILTER (WHERE name = $4),
		  count(DISTINCT user_id) FILTER (WHERE name = $5),
		  count(*) FILTER (WHERE name = $6)
		FROM events WHERE created_at > $1`,
		since, EventSignupStarted, EventSignupConfirmed,
		EventDigestSent, EventJobClicked, EventUnsubscribed,
	).Scan(&f.SignupsStarted, &f.SignupsConfirmed, &f.DigestsSent,
		&f.UsersWhoClicked, &f.Unsubscribes)
	if err != nil {
		return f, err
	}
	err = s.pool.QueryRow(ctx,
		`SELECT count(*) FROM users WHERE confirmed_at IS NOT NULL AND unsubscribed_at IS NULL`,
	).Scan(&f.ConfirmedAccounts)
	return f, err
}
