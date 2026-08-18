// Command digest is the nightly job: it enriches everything the ingester found
// since yesterday, then mails every confirmed subscriber the postings that match
// their filters. It shares the Postgres and the Claude-backed enricher with the
// API server via internal/server.
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

// enrichWindow is how far back to look for unjudged postings. Wider than a day
// so a night the cron did not run is caught up on the next one rather than
// leaving a permanent hole in the corpus.
const enrichWindow = 7 * 24 * time.Hour

// enrichLimit bounds one night's model spend. At ~1,500 new ids and ~300
// software roles a day this is several days of headroom; a backlog beyond it
// drains over subsequent nights instead of arriving as one surprising bill.
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
	log.Printf("digest run: %d subscribers, %d emails sent, %d roles delivered, %d had nothing new",
		summary.Subscribers, summary.EmailsSent, summary.JobsSent, summary.Skipped)
}
