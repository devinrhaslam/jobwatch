from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from time import sleep

from playwright.sync_api import sync_playwright

from jobwatch.engine import CompanyResult, default_fetch_page, run_company
from jobwatch.fetch import FetchError
from jobwatch.filters import FilterError, apply_filters_by_group
from jobwatch.models import FetchMode
from jobwatch.registry import SCRAPERS
from jobwatch.report import format_report, write_report

STATE_DIR = Path("state")
OUTPUT_DIR = Path("output")
INTER_COMPANY_DELAY_SECONDS = 1.0


BROWSER_MODES = (FetchMode.RENDERED, FetchMode.RENDERED_XHR)


class _BrowserPool:
    """Launches at most one browser per engine, on first use.

    Companies do not all render in the same engine — a board's bot filter may
    reject headless Chromium while serving headless Firefox — so a single shared
    browser is not enough. Launching lazily means a run that needs only Chromium
    never starts Firefox, and a failure to launch one engine is reported against
    the companies that need it rather than failing the whole run.
    """

    def __init__(self, playwright):
        self._playwright = playwright
        self._browsers: dict[str, object] = {}
        self._errors: dict[str, Exception] = {}

    def get(self, engine: str):
        if engine in self._browsers:
            return self._browsers[engine]
        if engine not in self._errors:
            try:
                self._browsers[engine] = getattr(self._playwright, engine).launch()
                return self._browsers[engine]
            except Exception as exc:
                self._errors[engine] = exc
        raise FetchError(f"browser launch failed for {engine}: {self._errors[engine]}")

    def close(self) -> None:
        for browser in self._browsers.values():
            try:
                browser.close()
            except Exception:  # a browser that already died must not fail the run
                pass


def _build_fetch_page(pool: _BrowserPool):
    def fetch_page(config, url):
        browser = pool.get(config.browser_engine) if config.fetch_mode in BROWSER_MODES else None
        return default_fetch_page(config, url, browser=browser)

    return fetch_page


def _run_companies(names, args, *, fetch_page) -> list[CompanyResult]:
    results = []
    for index, name in enumerate(names):
        scraper = SCRAPERS[name]
        if args.verbose:
            print(f"Checking {name}...", file=sys.stderr)
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
        if index < len(names) - 1:
            sleep(INTER_COMPANY_DELAY_SECONDS)
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
    parser.add_argument(
        "--all-roles",
        action="store_true",
        help="Report every new job, skipping the role-fit filter.",
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
        SCRAPERS[n].config.fetch_mode in BROWSER_MODES for n in names
    )

    if needs_browser:
        with sync_playwright() as pw:
            pool = _BrowserPool(pw)
            try:
                results = _run_companies(names, args, fetch_page=_build_fetch_page(pool))
            finally:
                pool.close()
    else:
        results = _run_companies(names, args, fetch_page=default_fetch_page)

    filter_failed = False
    if not args.all_roles:
        def report_drop(job, verdict):
            print(f"  dropped: {job.title} — {verdict.reason}", file=sys.stderr)

        pending = sum(len(r.new_jobs) for r in results)
        if pending:
            # Filtering runs after every company has been scraped and can take
            # a while, so say so rather than going silent at the end of a run.
            print(f"Classifying {pending} new jobs...", file=sys.stderr)
        try:
            # One pass over every company's new jobs, not one call per company:
            # batches fill across company boundaries instead of sending a
            # separate request for each company that has three new jobs.
            filtered = apply_filters_by_group(
                [r.new_jobs for r in results],
                cache_path=STATE_DIR / "filter_cache.json",
                on_drop=report_drop if args.verbose else None,
            )
            results = [
                replace(r, new_jobs=kept) for r, kept in zip(results, filtered)
            ]
        except FilterError as exc:
            # Snapshots are already written by this point, so these jobs will not
            # be reported again tomorrow. Show them unfiltered rather than lose them.
            print(f"Role filter failed: {exc}", file=sys.stderr)
            print("Reporting every new job unfiltered.", file=sys.stderr)
            filter_failed = True

    print(format_report(results))
    if not args.dry_run:
        report_path = write_report(results, output_dir=OUTPUT_DIR)
        if args.verbose:
            print(f"\nWrote {report_path}", file=sys.stderr)

    if filter_failed:
        return 1
    return 1 if any(r.status in ("failed", "blocked", "suspicious") for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
