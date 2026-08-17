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

// feedModel is a cheaper, faster model for the coarse "is this software
// engineering" question behind the public feed — simpler than the personal fit,
// over more jobs, so it does not need the top model. feedMaxTokens is modest
// because the output is just a short verdict per listing.
const feedModel = "claude-haiku-4-5-20251001"
const feedMaxTokens = 8192

const feedInstructions = `You are classifying job listings for a software-engineering job board. For each
listing, decide whether it is a software engineering role — a job whose core work
is writing and building software.

Return relevant=true for software engineering roles of any specialty and level:
software engineer, backend, frontend, full-stack, mobile (iOS/Android), embedded
or firmware, systems, platform, infrastructure, SRE, DevOps, security engineer,
and machine-learning or data ENGINEERS. Include internships, new grad, and
staff/principal, anywhere in the world.

Return relevant=false for everything else, including roles that are technical or
adjacent but are not software engineering:
- data scientists, machine-learning / AI / applied / research SCIENTISTS,
  quantitative researchers, data analysts, analytics roles
- product, program, or project management, and engineering management
- design (UX/UI/graphic), sales, marketing, recruiting, HR, finance, legal,
  customer success, IT support, operations, warehouse and retail roles
- non-software engineering: mechanical, electrical, hardware, manufacturing,
  civil, and ERP/SAP functional roles

The distinction that matters: an engineer who builds software is in; a scientist,
researcher, analyst, manager, or non-software engineer is out — even if the title
contains "Engineer" or the role is technical. Give a reason of at most 8 words.
Return one verdict per listing using the index shown, as JSON:
{"verdicts":[{"index":<int>,"relevant":<bool>,"reason":<string>}]} and nothing else.`

// claudeClassifier asks Claude to judge listings. Batches of 50 keep any single
// request bounded; a batch that comes back missing a listing is re-asked for
// just the gaps rather than failing.
type claudeClassifier struct {
	client anthropic.Client
}

func newClaudeClassifier() *claudeClassifier {
	return &claudeClassifier{client: anthropic.NewClient()}
}

// Classify judges each job against a candidate profile — the personal fit filter,
// a faithful port of jobwatch/filters.py.
func (c *claudeClassifier) Classify(ctx context.Context, profile string, jobs []Job) ([]Verdict, error) {
	system := strings.ReplaceAll(fitInstructions, "{profile}", profile)
	return c.classifyAll(ctx, fitModel, fitMaxTokens, system, jobs)
}

// ClassifySoftware judges whether each job is a software engineering role, for
// the public feed. No profile, no location or personal preferences.
func (c *claudeClassifier) ClassifySoftware(ctx context.Context, jobs []Job) ([]Verdict, error) {
	return c.classifyAll(ctx, feedModel, feedMaxTokens, feedInstructions, jobs)
}

func (c *claudeClassifier) classifyAll(ctx context.Context, model string, maxTokens int, system string, jobs []Job) ([]Verdict, error) {
	out := make([]Verdict, 0, len(jobs))
	for start := 0; start < len(jobs); start += fitBatchSize {
		end := start + fitBatchSize
		if end > len(jobs) {
			end = len(jobs)
		}
		verdicts, err := c.classifyBatch(ctx, model, maxTokens, system, jobs[start:end], 0)
		if err != nil {
			return nil, err
		}
		out = append(out, verdicts...)
	}
	return out, nil
}

func (c *claudeClassifier) classifyBatch(ctx context.Context, model string, maxTokens int, system string, jobs []Job, attempt int) ([]Verdict, error) {
	var listings strings.Builder
	for i, j := range jobs {
		loc := ""
		if j.Location != nil && *j.Location != "" {
			loc = " (" + *j.Location + ")"
		}
		fmt.Fprintf(&listings, "%d. %s — %s%s\n", i, j.Title, j.Company, loc)
	}

	msg, err := c.client.Messages.New(ctx, anthropic.MessageNewParams{
		Model:     anthropic.Model(model),
		MaxTokens: int64(maxTokens),
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
		retried, err := c.classifyBatch(ctx, model, maxTokens, system, gaps, attempt+1)
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
