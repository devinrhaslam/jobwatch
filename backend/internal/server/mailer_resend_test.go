package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestResendMailerSendsLoginLink(t *testing.T) {
	var got struct {
		From    string   `json:"from"`
		To      []string `json:"to"`
		Subject string   `json:"subject"`
		HTML    string   `json:"html"`
		Text    string   `json:"text"`
	}
	var authHeader string
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		authHeader = r.Header.Get("Authorization")
		_ = json.NewDecoder(r.Body).Decode(&got)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"id":"email_123"}`))
	}))
	defer ts.Close()

	m := newResendMailer("test-key", "jobwatch <alerts@example.com>", "https://app.example")
	m.endpoint = ts.URL

	link := "https://app.example/verify?token=abc"
	if err := m.SendLoginLink(context.Background(), "user@example.com", link); err != nil {
		t.Fatalf("send: %v", err)
	}

	if authHeader != "Bearer test-key" {
		t.Errorf("auth header = %q, want Bearer test-key", authHeader)
	}
	if got.From != "jobwatch <alerts@example.com>" || len(got.To) != 1 || got.To[0] != "user@example.com" {
		t.Errorf("from/to = %q / %v", got.From, got.To)
	}
	if !strings.Contains(got.HTML, link) || !strings.Contains(got.Text, link) {
		t.Errorf("link missing from body: html=%q text=%q", got.HTML, got.Text)
	}
}

func TestResendMailerSurfacesAPIErrors(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusUnprocessableEntity)
		_, _ = w.Write([]byte(`{"message":"domain not verified"}`))
	}))
	defer ts.Close()

	m := newResendMailer("k", "from@example.com", "https://app.example")
	m.endpoint = ts.URL
	err := m.SendLoginLink(context.Background(), "u@e.com", "https://x")
	if err == nil || !strings.Contains(err.Error(), "422") {
		t.Fatalf("expected a 422 error surfaced, got %v", err)
	}
}
