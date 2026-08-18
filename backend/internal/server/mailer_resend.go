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

func (m *resendMailer) send(ctx context.Context, to, subject, htmlBody, textBody string, headers map[string]string) error {
	body := map[string]any{
		"from":    m.from,
		"to":      []string{to},
		"subject": subject,
		"html":    htmlBody,
		"text":    textBody,
	}
	if len(headers) > 0 {
		body["headers"] = headers
	}
	payload, err := json.Marshal(body)
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
	return m.send(ctx, email, "Your jobwatch sign-in link", body, text, nil)
}

// SendDigest transmits a rendered digest.
//
// The List-Unsubscribe headers are not optional decoration. Gmail and Yahoo's
// bulk sender rules expect a one-click opt-out, and mail clients surface it as a
// native "Unsubscribe" button next to the sender — which is the difference
// between a bored reader unsubscribing (free) and reporting spam (expensive, and
// charged against the sending domain forever).
func (m *resendMailer) SendDigest(ctx context.Context, sub Subscriber, c DigestContent) error {
	headers := map[string]string{}
	if c.UnsubURL != "" {
		headers["List-Unsubscribe"] = "<" + c.UnsubURL + ">"
		headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
	}
	return m.send(ctx, sub.Email, digestSubject(c), digestHTML(c), digestText(c), headers)
}
