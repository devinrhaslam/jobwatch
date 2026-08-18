// Command logocheck reports how many tracked companies resolve to a real logo.
//
// It exists because this failed silently once already: the icons were served by
// Clearbit's free logo API, that service was withdrawn, and every company on the
// site quietly became a lettered monogram for weeks. Nothing broke, nothing
// logged, and the fallback did its job too well to notice.
//
// Run it after adding companies to companies.txt, or after changing
// JOBWATCH_LOGO_TEMPLATE:
//
//	go run ./cmd/logocheck ../companies.txt
//
// Or straight from the database:
//
//	psql "$JOBWATCH_DATABASE_URL" -t -A -c \
//	    'SELECT DISTINCT company FROM jobs ORDER BY company' > /tmp/companies.txt
//	go run ./cmd/logocheck /tmp/companies.txt
//
// A handful of misses is normal and fine — some real domains simply have no icon
// on file, and those render as monograms by design. A sudden collapse to near
// zero means the provider is gone again.
package main

import (
	"bufio"
	"fmt"
	"net/http"
	"os"
	"sort"
	"sync"
	"time"

	"github.com/applications/backend/internal/server"
)

const concurrency = 12

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: logocheck <file with one company name per line>")
		os.Exit(2)
	}

	names, err := readNames(os.Args[1])
	if err != nil {
		fmt.Fprintf(os.Stderr, "reading %s: %v\n", os.Args[1], err)
		os.Exit(1)
	}

	client := &http.Client{Timeout: 12 * time.Second}
	var (
		mu       sync.Mutex
		resolved int
		failures []string
		wg       sync.WaitGroup
	)
	sem := make(chan struct{}, concurrency)

	for _, name := range names {
		wg.Add(1)
		go func(name string) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			ok := false
			if u := server.LogoURL(name); u != "" {
				resp, err := client.Get(u)
				if err == nil {
					ok = resp.StatusCode < 300
					resp.Body.Close()
				}
			}

			mu.Lock()
			defer mu.Unlock()
			if ok {
				resolved++
			} else {
				failures = append(failures, name)
			}
		}(name)
	}
	wg.Wait()

	total := len(names)
	fmt.Printf("resolved %d / %d (%.1f%%)\n", resolved, total, 100*float64(resolved)/float64(total))
	if len(failures) > 0 {
		sort.Strings(failures)
		fmt.Printf("\nfalling back to a monogram (%d):\n", len(failures))
		for _, name := range failures {
			fmt.Printf("  %-32s %s\n", name, server.LogoURL(name))
		}
		fmt.Println("\nFix by adding the real domain to domainOverrides in internal/server/logo.go.")
	}
}

func readNames(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	var names []string
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		if line := sc.Text(); line != "" {
			names = append(names, line)
		}
	}
	return names, sc.Err()
}
