from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from jobwatch.engine import CompanyResult, default_fetch_page, run_company
from jobwatch.models import FetchMode
from jobwatch.registry import SCRAPERS
from jobwatch.report import format_report, write_report

STATE_DIR = Path("state")
OUTPUT_DIR = Path("output")


def _build_fetch_page(browser):
    def fetch_page(config, url):
        return default_fetch_page(config, url, browser=browser)

    return fetch_page


def _run_companies(
    names, args, *, fetch_page, browser_error: Exception | None
) -> list[CompanyResult]:
    results = []
    for name in names:
        scraper = SCRAPERS[name]
        if args.verbose:
            print(f"Checking {name}...", file=sys.stderr)
        if browser_error is not None and scraper.config.fetch_mode is FetchMode.RENDERED:
            results.append(
                CompanyResult(
                    name, "failed", [], 0, f"browser launch failed: {browser_error}"
                )
            )
            continue
        try:
            result = run_company(
                scraper,
                state_dir=STATE_DIR,
                dry_run=args.dry_run,
                fetch_page=fetch_page,
            )
        except Exception as exc:  # isolate one company's crash from the rest
            result = CompanyResult(name, "failed", [], 0, f"unexpected error: {exc}")
        results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check tracked companies for newly posted jobs."
    )
    parser.add_argument(
        "--company",
        action="append",
        dest="companies",
        help="Limit the run to this company (repeatable). Defaults to all registered companies.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and report without writing snapshot state.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print per-company diagnostics to stderr."
    )
    args = parser.parse_args(argv)

    names = args.companies or sorted(SCRAPERS)
    unknown = [n for n in names if n not in SCRAPERS]
    if unknown:
        print(
            f"Unknown companies: {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(SCRAPERS))}",
            file=sys.stderr,
        )
        return 2

    needs_browser = any(
        SCRAPERS[n].config.fetch_mode is FetchMode.RENDERED for n in names
    )

    if needs_browser:
        with sync_playwright() as pw:
            browser = None
            browser_error: Exception | None = None
            try:
                browser = pw.chromium.launch()
            except Exception as exc:
                browser_error = exc
            try:
                results = _run_companies(
                    names,
                    args,
                    fetch_page=_build_fetch_page(browser),
                    browser_error=browser_error,
                )
            finally:
                if browser is not None:
                    browser.close()
    else:
        results = _run_companies(
            names, args, fetch_page=default_fetch_page, browser_error=None
        )

    print(format_report(results))
    if not args.dry_run:
        report_path = write_report(results, output_dir=OUTPUT_DIR)
        if args.verbose:
            print(f"\nWrote {report_path}", file=sys.stderr)

    return 1 if any(r.status in ("failed", "blocked") for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
