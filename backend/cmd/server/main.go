// Command server is the jobwatch read API: a thin HTTP layer over the Postgres
// `jobs` and `company_runs` tables the Python ingestion worker writes. The two
// services share nothing but the database — this process never calls Python.
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/applications/backend/internal/server"
)

func main() {
	// Same variable the Python side reads, so both services point at one
	// database with one env var.
	dsn := os.Getenv("JOBWATCH_DATABASE_URL")
	if dsn == "" {
		log.Fatal("JOBWATCH_DATABASE_URL is required")
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	srv, err := server.New(ctx, dsn)
	if err != nil {
		log.Fatalf("startup: %v", err)
	}
	defer srv.Close()

	httpSrv := &http.Server{
		Addr:              ":" + port,
		Handler:           srv.Routes(),
		ReadHeaderTimeout: 5 * time.Second,
	}
	log.Printf("jobwatch backend listening on :%s", port)
	log.Fatal(httpSrv.ListenAndServe())
}
