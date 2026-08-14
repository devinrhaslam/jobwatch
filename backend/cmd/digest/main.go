// Command digest is the alerting loop, run on a schedule (e.g. a Fargate
// scheduled task): it matches every eligible user against fresh postings and
// emails each their new matches, once. It shares the Postgres and the
// Claude-backed classifier with the API server via internal/server.
package main

import (
	"context"
	"log"
	"os"
	"time"

	"github.com/applications/backend/internal/server"
)

func main() {
	dsn := os.Getenv("JOBWATCH_DATABASE_URL")
	if dsn == "" {
		log.Fatal("JOBWATCH_DATABASE_URL is required")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
	defer cancel()

	srv, err := server.New(ctx, dsn)
	if err != nil {
		log.Fatalf("startup: %v", err)
	}
	defer srv.Close()

	summary, err := srv.RunDigests(ctx)
	if err != nil {
		log.Fatalf("digest run: %v", err)
	}
	log.Printf("digest run: %d users processed, %d emails sent, %d matches delivered",
		summary.Users, summary.EmailsSent, summary.MatchesSent)
}
