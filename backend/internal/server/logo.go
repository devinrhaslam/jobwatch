package server

import (
	"net/url"
	"os"
	"strings"
)

// domainOverrides covers the companies where "lowercase, strip non-alphanumeric,
// append .com" guesses the wrong domain. Everything else uses the guess and, if
// no logo comes back, falls back to a monogram — so a miss is a tidy initial,
// never a broken image.
//
// This lives in Go rather than in the React component because the digest email
// needs the same answer, and two copies of this map would drift.
var domainOverrides = map[string]string{
	"Google DeepMind":                "deepmind.com",
	"Hims & Hers":                    "hims.com",
	"monday.com":                     "monday.com",
	"Character.AI":                   "character.ai",
	"Checkout.com":                   "checkout.com",
	"1X Technologies":                "1x.tech",
	"X":                              "x.com",
	"Two Sigma":                      "twosigma.com",
	"Match Group":                    "mtch.com",
	"Rocket Lab":                     "rocketlabusa.com",
	"Electronic Arts":                "ea.com",
	"Take-Two Interactive":           "take2games.com",
	"Sony Interactive Entertainment": "sony.com",
	"Walmart Global Tech":            "walmart.com",
	"Hudson River Trading":           "hudsonrivertrading.com",

	// The AI/startup cohort, which overwhelmingly is not on a .com. Measured
	// against the live icon service rather than guessed; without these, roughly
	// one company in eight rendered as a monogram.
	"Booking.com":            "booking.com",
	"ElevenLabs":             "elevenlabs.io",
	"Confluent":              "confluent.io",
	"Scale AI":               "scale.com",
	"Reflection AI":          "reflection.ai",
	"Skild AI":               "skild.ai",
	"Figure AI":              "figure.ai",
	"Fireworks AI":           "fireworks.ai",
	"Harvey":                 "harvey.ai",
	"Cadence Design Systems": "cadence.com",
	"Thinking Machines Lab":  "thinkingmachines.ai",
	"Together AI":            "together.ai",
	"Lambda":                 "lambdalabs.com",
	"Luma AI":                "lumalabs.ai",
	"Varda Space Industries": "varda.com",
	"Wayve":                  "wayve.ai",
	"Wiz":                    "wiz.io",
	"Poolside":               "poolside.ai",
	"Planet Labs":            "planet.com",
	"Zed":                    "zed.dev",
	"xAI":                    "x.ai",
	"Synthesia":              "synthesia.io",
	"Firefly Aerospace":      "fireflyspace.com",
	"Tempus AI":              "tempus.com",
	"Warp":                   "warp.dev",
	"Oura":                   "ouraring.com",
	"Physical Intelligence":  "physicalintelligence.company",
}

// logoTemplate builds a logo URL from a domain. It is configurable because the
// last provider (Clearbit's free logo API) was withdrawn and every icon silently
// became a monogram — a swap should be one environment variable, not a deploy.
// {domain} is replaced with the resolved domain.
//
// The default is DuckDuckGo's icon service: no API key, no redirect hop (which
// some mail clients will not follow), and served over HTTPS.
const defaultLogoTemplate = "https://icons.duckduckgo.com/ip3/{domain}.ico"

func logoTemplate() string {
	if t := os.Getenv("JOBWATCH_LOGO_TEMPLATE"); t != "" {
		return t
	}
	return defaultLogoTemplate
}

// domainFor resolves a company name to its best-guess web domain.
func domainFor(company string) string {
	if d, ok := domainOverrides[company]; ok {
		return d
	}
	var b strings.Builder
	for _, r := range strings.ToLower(company) {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			b.WriteRune(r)
		}
	}
	if b.Len() == 0 {
		return ""
	}
	return b.String() + ".com"
}

// LogoURL is the company's icon, or "" when the name yields no usable domain —
// in which case callers show a monogram.
func LogoURL(company string) string {
	domain := domainFor(company)
	if domain == "" {
		return ""
	}
	return strings.ReplaceAll(logoTemplate(), "{domain}", url.PathEscape(domain))
}

// JobView is a Job as the API serves it: the stored row plus the presentation
// facts every client would otherwise recompute. Embedding Job keeps the existing
// JSON field names unchanged.
type JobView struct {
	Job
	LogoURL string `json:"logo_url"`
}

func decorate(jobs []Job) []JobView {
	out := make([]JobView, len(jobs))
	for i, j := range jobs {
		out[i] = JobView{Job: j, LogoURL: LogoURL(j.Company)}
	}
	return out
}
