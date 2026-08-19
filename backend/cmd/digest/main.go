// Command digest is the tail of the ingestion cycle: it enriches everything the
// scraper has found since the last pass, then mails the subscribers who are due
// a digest the postings that match their filters. It shares the Postgres and the
// Claude-backed enricher with the API server via internal/server.
//
// It runs on the pipeline's cadence (every two hours), which is deliberately not
// the email cadence. Enrichment wants to keep up with the scraper so the public
// feed is live; a person wants roughly one digest a day. RunDigests holds that
// second line — see Subscribers and JOBWATCH_DIGEST_INTERVAL_HOURS — so running
// this often does not mean emailing this often.
//
// Enrichment runs first and deliberately blocks the digests: a posting with no
// verdict yet is invisible to the digest query, so sending before enriching
// would quietly skip the newest roles — the exact ones the product exists to
// deliver.
package main

import (
	"context"
	"log"
	"os"
	"time"

	"github.com/applications/backend/internal/server"
)

// enrichWindow is how far back to look for unjudged postings. Far wider than one
// cycle so a stretch of failed runs is caught up on the next success rather than
// leaving a permanent hole in the corpus.
const enrichWindow = 7 * 24 * time.Hour

// enrichLimit bounds one run's model spend. At ~1,500 new ids and ~300 software
// roles a day this is several days of headroom even on a two-hourly cycle, where
// a typical run sees a fraction of that; a backlog beyond it drains over
// subsequent runs instead of arriving as one surprising bill.
const enrichLimit = 5000

func main() {
	dsn := os.Getenv("JOBWATCH_DATABASE_URL")
	if dsn == "" {
		log.Fatal("JOBWATCH_DATABASE_URL is required")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Minute)
	defer cancel()

	srv, err := server.New(ctx, dsn)
	if err != nil {
		log.Fatalf("startup: %v", err)
	}
	defer srv.Close()

	n, err := srv.EnrichNew(ctx, time.Now().Add(-enrichWindow), enrichLimit)
	if err != nil {
		// A failed enrichment means today's postings have no verdicts, so the
		// digests would be missing exactly the newest roles. Stop rather than
		// send a digest that is quietly incomplete and advances everyone's
		// cursor past the postings it skipped.
		log.Fatalf("enrichment: %v", err)
	}
	log.Printf("enrichment: judged %d new postings", n)

	summary, err := srv.RunDigests(ctx)
	if err != nil {
		log.Fatalf("digest run: %v", err)
	}
	// "subscribers" here is those *due* a digest this run, not the whole list —
	// on a two-hourly cycle most runs will legitimately report zero.
	log.Printf("digest run: %d subscribers due, %d emails sent, %d roles delivered, %d had nothing new",
		summary.Subscribers, summary.EmailsSent, summary.JobsSent, summary.Skipped)
}
