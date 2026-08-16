package server

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"html"
	"io"
	"net/http"
	"strings"
	"time"
)

const resendEndpoint = "https://api.resend.com/emails"

// resendMailer sends transactional email through Resend's HTTP API. It is used
// when RESEND_API_KEY is set; otherwise the app falls back to the dev logMailer.
type resendMailer struct {
	apiKey   string
	from     string // e.g. "jobwatch <alerts@yourdomain.com>"
	appURL   string // for the manage-account footer
	endpoint string
	client   *http.Client
}

func newResendMailer(apiKey, from, appURL string) *resendMailer {
	return &resendMailer{
		apiKey:   apiKey,
		from:     from,
		appURL:   appURL,
		endpoint: resendEndpoint,
		client:   &http.Client{Timeout: 15 * time.Second},
	}
}

func (m *resendMailer) send(ctx context.Context, to, subject, htmlBody, textBody string) error {
	payload, err := json.Marshal(map[string]any{
		"from":    m.from,
		"to":      []string{to},
		"subject": subject,
		"html":    htmlBody,
		"text":    textBody,
	})
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, m.endpoint, bytes.NewReader(payload))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+m.apiKey)
	req.Header.Set("Content-Type", "application/json")

	resp, err := m.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("resend returned %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	return nil
}

func (m *resendMailer) SendLoginLink(ctx context.Context, email, link string) error {
	text := fmt.Sprintf(
		"Sign in to jobwatch:\n\n%s\n\nThis link expires in 15 minutes. If you didn't request it, ignore this email.",
		link,
	)
	body := fmt.Sprintf(
		`<p>Sign in to jobwatch:</p>`+
			`<p><a href="%s">Sign in to jobwatch</a></p>`+
			`<p style="color:#6b7280;font-size:13px">This link expires in 15 minutes. `+
			`If you didn't request it, you can ignore this email.</p>`,
		html.EscapeString(link),
	)
	return m.send(ctx, email, "Your jobwatch sign-in link", body, text)
}

func (m *resendMailer) SendDigest(ctx context.Context, email string, matches []Match) error {
	noun := "match"
	if len(matches) != 1 {
		noun = "matches"
	}
	subject := fmt.Sprintf("%d new %s at your companies", len(matches), noun)

	var text, body strings.Builder
	text.WriteString("New roles matching your profile:\n\n")
	body.WriteString(`<p>New roles matching your profile:</p><ul>`)
	for _, mt := range matches {
		loc := ""
		if mt.Location != nil && *mt.Location != "" {
			loc = " · " + *mt.Location
		}
		fmt.Fprintf(&text, "- %s — %s%s\n  %s\n\n", mt.Title, mt.Company, loc, mt.URL)
		fmt.Fprintf(&body, `<li><a href="%s">%s</a> — %s%s</li>`,
			html.EscapeString(mt.URL), html.EscapeString(mt.Title),
			html.EscapeString(mt.Company), html.EscapeString(loc))
	}
	body.WriteString(`</ul>`)

	// A minimal opt-out: deleting the account stops all email. A one-click
	// unsubscribe and a physical mailing address are still needed for CAN-SPAM
	// before sending at scale (see DEPLOY.md).
	fmt.Fprintf(&text, "\nYou're receiving this because you signed up for jobwatch. Manage or delete your account: %s\n", m.appURL)
	fmt.Fprintf(&body, `<p style="color:#6b7280;font-size:12px">You're receiving this because you signed up for jobwatch. `+
		`<a href="%s">Manage or delete your account</a>.</p>`, html.EscapeString(m.appURL))

	return m.send(ctx, email, subject, body.String(), text.String())
}
