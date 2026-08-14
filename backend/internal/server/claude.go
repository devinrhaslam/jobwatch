package server

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/anthropics/anthropic-sdk-go"
)

const (
	fitBatchSize  = 50
	fitMaxTokens  = 16000
	fitMaxRetries = 2
)

// claudeClassifier is the real fit filter: it asks Claude to judge each listing
// against the profile, a faithful port of jobwatch/filters.py. Batches of 50
// keep any single request bounded; a batch that comes back missing a listing is
// re-asked for just the gaps rather than failing the run.
type claudeClassifier struct {
	client anthropic.Client
}

func newClaudeClassifier() *claudeClassifier {
	return &claudeClassifier{client: anthropic.NewClient()}
}

func (c *claudeClassifier) Classify(ctx context.Context, profile string, jobs []Job) ([]Verdict, error) {
	out := make([]Verdict, 0, len(jobs))
	for start := 0; start < len(jobs); start += fitBatchSize {
		end := start + fitBatchSize
		if end > len(jobs) {
			end = len(jobs)
		}
		verdicts, err := c.classifyBatch(ctx, profile, jobs[start:end], 0)
		if err != nil {
			return nil, err
		}
		out = append(out, verdicts...)
	}
	return out, nil
}

func (c *claudeClassifier) classifyBatch(ctx context.Context, profile string, jobs []Job, attempt int) ([]Verdict, error) {
	var listings strings.Builder
	for i, j := range jobs {
		loc := ""
		if j.Location != nil && *j.Location != "" {
			loc = " (" + *j.Location + ")"
		}
		fmt.Fprintf(&listings, "%d. %s — %s%s\n", i, j.Title, j.Company, loc)
	}

	system := strings.ReplaceAll(fitInstructions, "{profile}", profile)
	msg, err := c.client.Messages.New(ctx, anthropic.MessageNewParams{
		Model:     anthropic.Model(fitModel),
		MaxTokens: fitMaxTokens,
		System:    []anthropic.TextBlockParam{{Text: system}},
		Messages: []anthropic.MessageParam{
			anthropic.NewUserMessage(anthropic.NewTextBlock(listings.String())),
		},
	})
	if err != nil {
		return nil, fmt.Errorf("classification request failed: %w", err)
	}

	var text strings.Builder
	for _, block := range msg.Content {
		if block.Type == "text" {
			text.WriteString(block.Text)
		}
	}

	var parsed struct {
		Verdicts []struct {
			Index    int    `json:"index"`
			Relevant bool   `json:"relevant"`
			Reason   string `json:"reason"`
		} `json:"verdicts"`
	}
	if err := json.Unmarshal([]byte(extractJSON(text.String())), &parsed); err != nil {
		return nil, fmt.Errorf("could not parse classification response: %w", err)
	}

	byIndex := make(map[int]Verdict, len(parsed.Verdicts))
	for _, v := range parsed.Verdicts {
		byIndex[v.Index] = Verdict{Keep: v.Relevant, Reason: v.Reason}
	}

	var missing []int
	for i := range jobs {
		if _, ok := byIndex[i]; !ok {
			missing = append(missing, i)
		}
	}
	if len(missing) > 0 {
		if attempt >= fitMaxRetries {
			return nil, fmt.Errorf("classification omitted %d of %d listings after %d attempts",
				len(missing), len(jobs), attempt+1)
		}
		gaps := make([]Job, len(missing))
		for k, i := range missing {
			gaps[k] = jobs[i]
		}
		retried, err := c.classifyBatch(ctx, profile, gaps, attempt+1)
		if err != nil {
			return nil, err
		}
		for k, i := range missing {
			byIndex[i] = retried[k]
		}
	}

	out := make([]Verdict, len(jobs))
	for i := range jobs {
		out[i] = byIndex[i]
	}
	return out, nil
}

// extractJSON returns the outermost {...} span, tolerating a model that wraps
// the object in prose or a markdown fence despite being asked not to.
func extractJSON(s string) string {
	start := strings.Index(s, "{")
	end := strings.LastIndex(s, "}")
	if start >= 0 && end > start {
		return s[start : end+1]
	}
	return s
}
