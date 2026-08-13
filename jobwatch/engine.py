from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from jobwatch import diff, state
from jobwatch.fetch import (
    FetchBlocked,
    FetchError,
    fetch_form_post,
    fetch_json_post,
    fetch_rendered,
    fetch_rendered_xhr,
    fetch_static,
)
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

MAX_PAGES = 20
# Default ceiling on per-job detail fetches in one run. Only scrapers that
# implement Scraper.detail_url make these at all.
MAX_ENRICHMENT_FETCHES = 120
# Paused between pages of the same company. A paginated board is the only place
# this tool makes rapid back-to-back requests — Netflix reads 49 pages on every
# run and a Workday seed runs to ~196 — which is both impolite and the most
# likely source of a transient fetch failure. One company failing an entire run
# because its first page happened to be the unlucky request is not a good trade
# for a few saved seconds.
INTER_PAGE_DELAY_SECONDS = 0.3
SUSPICIOUS_NEW_JOB_RATIO = 0.8
MIN_JOBS_FOR_SUSPICIOUS_CHECK = 20
logger = logging.getLogger(__name__)

FetchPage = Callable[[CompanyConfig, str], str]
# Called once per network request a company makes, so a caller can show that a
# long-running company is still moving. Boards differ by three orders of
# magnitude in request count — one for Greenhouse, ~185 for Microsoft — and
# without this a run looks identically stalled for either.
OnRequest = Callable[[], None]


class ParseError(Exception):
    """Raised when a scraper's parse() call raises against page markup,
    e.g. a site redesign breaking a BeautifulSoup selector."""


def default_fetch_page(config: CompanyConfig, url: str, *, browser=None) -> str:
    if config.fetch_mode is FetchMode.STATIC:
        return fetch_static(url, headers=config.request_headers)
    if config.fetch_mode is FetchMode.JSON_POST:
        return fetch_json_post(url, headers=config.request_headers)
    if config.fetch_mode is FetchMode.FORM_POST:
        return fetch_form_post(url, headers=config.request_headers)
    if config.fetch_mode is FetchMode.RENDERED_XHR:
        return fetch_rendered_xhr(
            url,
            capture_response_url=config.capture_response_url,
            engine=config.browser_engine,
            browser=browser,
        )
    return fetch_rendered(url, wait_for_selector=config.wait_for_selector, browser=browser)


@dataclass
class CompanyResult:
    company: str
    status: str
    new_jobs: list[Job]
    total_jobs: int
    detail: str | None = None


def run_company(
    scraper: Scraper,
    *,
    state_dir: Path,
    dry_run: bool = False,
    fetch_page: FetchPage = default_fetch_page,
    on_request: OnRequest | None = None,
) -> CompanyResult:
    config = scraper.config
    is_seed_run = not state.snapshot_exists(config.name, state_dir)
    snapshot = state.load_snapshot(config.name, state_dir)

    try:
        jobs, truncation_detail, stopped_on_known_page = _fetch_all_pages(
            scraper,
            config,
            known_ids=None if is_seed_run else set(snapshot),
            fetch_page=fetch_page,
            on_request=on_request,
        )
    except FetchBlocked as exc:
        return CompanyResult(config.name, "blocked", [], 0, str(exc))
    except FetchError as exc:
        return CompanyResult(config.name, "failed", [], 0, str(exc))
    except ParseError as exc:
        return CompanyResult(config.name, "failed", [], 0, str(exc))

    if not jobs:
        if is_seed_run:
            # Persisting an empty seed would look identical, on every future
            # run, to "existing snapshot" — permanently silencing a company
            # whose scraper was broken from day one. Refuse to persist so the
            # next run retries the seed instead of locking in the failure.
            return CompanyResult(
                config.name,
                "failed",
                [],
                0,
                "seed run produced zero jobs; the parser or page markup is suspect",
            )
        return CompanyResult(
            config.name,
            "failed",
            [],
            0,
            "parser returned zero jobs against an existing snapshot",
        )

    if is_seed_run and truncation_detail:
        # A truncated seed is as damaging as an empty one, just quieter: it
        # records part of the board as the whole of it, so every posting the
        # run never reached is reported as new on the next run — hundreds of
        # weeks-old jobs presented as today's. Refuse the seed and let the next
        # run start it over.
        return CompanyResult(
            config.name,
            "failed",
            [],
            len(jobs),
            f"seed run was incomplete, so it was not saved: {truncation_detail}",
        )

    new_jobs = diff.find_new_jobs(jobs, snapshot)

    # Enrich before the snapshot is written and before run.py's role filter
    # sees these jobs, so both work from the real title rather than whatever
    # placeholder a thin listing carried.
    new_jobs, jobs = _enrich_new_jobs(
        scraper, config, new_jobs, jobs, fetch_page=fetch_page, on_request=on_request
    )

    # An empty snapshot is deliberately exempt: this guard detects a site
    # changing its job ID scheme, which is only knowable by comparison against
    # jobs already recorded. With nothing recorded, an all-new run is expected
    # (a company that had no openings when it was first seeded), so flagging it
    # would be a false alarm that withholds genuinely new jobs.
    #
    # A run that early-stopped is exempt for the same reason. The ratio below is
    # new jobs over jobs *read*, and on a newest-first board the read stops at
    # the first page holding nothing unseen — so a company that genuinely posted
    # a lot reads mostly-new pages and the ratio approaches 1 by construction.
    # Microsoft tripped this at 179 of 200 while posting 179 jobs in two days,
    # its ids unchanged and 21 known ones sitting on the page that ended the
    # run. Reaching a page of entirely known jobs is itself proof the scheme
    # still matches, which is exactly what this guard is trying to establish.
    if (
        snapshot
        and jobs
        and not stopped_on_known_page
        and len(jobs) >= MIN_JOBS_FOR_SUSPICIOUS_CHECK
        and len(new_jobs) / len(jobs) >= SUSPICIOUS_NEW_JOB_RATIO
    ):
        return CompanyResult(
            config.name,
            "suspicious",
            new_jobs,
            len(jobs),
            f"{len(new_jobs)} of {len(jobs)} jobs are new; likely an ID/URL scheme change",
        )

    if not dry_run:
        merged = state.merge_snapshot(snapshot, jobs)
        state.save_snapshot(config.name, merged, state_dir)

    status = "seeded" if is_seed_run else "ok"
    reported_new = [] if is_seed_run else new_jobs
    return CompanyResult(config.name, status, reported_new, len(jobs), truncation_detail)


def _enrich_new_jobs(
    scraper: Scraper,
    config: CompanyConfig,
    new_jobs: list[Job],
    all_jobs: list[Job],
    *,
    fetch_page: FetchPage,
    on_request: OnRequest | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[Job], list[Job]]:
    """Replace each new job with a version read from its own posting page.

    Enrichment is best-effort by design. A board is still worth reporting with a
    thin title and a working link, so a detail page that fails to fetch or parse
    leaves that job as it was and the run continues — the alternative, failing
    the company, would throw away the diff that is the whole point of the run.
    """
    if not new_jobs:
        return new_jobs, all_jobs

    limit = config.max_enrichment_fetches or MAX_ENRICHMENT_FETCHES
    delay = (
        config.inter_page_delay_seconds
        if config.inter_page_delay_seconds is not None
        else INTER_PAGE_DELAY_SECONDS
    )
    enriched: dict[str, Job] = {}
    fetches = 0
    for job in new_jobs:
        if fetches >= limit:
            logger.warning(
                "Stopped enriching %s at the %d-fetch ceiling; %d new jobs keep "
                "their listing data",
                config.name,
                limit,
                len(new_jobs) - fetches,
            )
            break
        url = scraper.detail_url(job)
        if not url:
            continue
        if fetches:
            sleep(delay)
        fetches += 1
        if on_request:
            on_request()
        try:
            payload = fetch_page(config, url)
            enriched[job.job_id] = scraper.parse_detail(payload, job)
        except Exception:  # fetch failure, parse failure — all non-fatal here
            logger.warning(
                "Could not enrich %s job %s from %s; keeping listing data",
                config.name,
                job.job_id,
                url,
                exc_info=True,
            )

    if not enriched:
        return new_jobs, all_jobs
    return (
        [enriched.get(job.job_id, job) for job in new_jobs],
        [enriched.get(job.job_id, job) for job in all_jobs],
    )


def _fetch_all_pages(
    scraper: Scraper,
    config: CompanyConfig,
    *,
    known_ids: set[str] | None,
    fetch_page: FetchPage,
    on_request: OnRequest | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[Job], str | None]:
    all_jobs: dict[str, Job] = {}
    url = config.career_url
    truncated: str | None = None
    # Whether pagination ended because a page contained no job the snapshot did
    # not already hold. Reaching that page is proof the board's ids still line
    # up with the recorded ones, which is what the suspicious-run check needs to
    # know; see run_company.
    stopped_on_known_page = False
    max_pages = config.max_pages or MAX_PAGES
    page_delay = (
        config.inter_page_delay_seconds
        if config.inter_page_delay_seconds is not None
        else INTER_PAGE_DELAY_SECONDS
    )
    for page_number in range(max_pages):
        if page_number:
            sleep(page_delay)
        if on_request:
            on_request()
        try:
            payload = fetch_page(config, url)
        except (FetchBlocked, FetchError):
            if not all_jobs:
                raise
            logger.warning(
                "Stopping pagination for %s after a later page failed to fetch: %s",
                config.name,
                url,
                exc_info=True,
            )
            truncated = f"pagination stopped early: a later page failed to fetch ({url})"
            break
        try:
            page_jobs = scraper.parse(payload)
        except Exception as exc:
            if not all_jobs:
                raise ParseError(
                    f"parser raised while parsing {config.name} at {url}: {exc}"
                ) from exc
            logger.warning(
                "Stopping pagination for %s after a later page failed to parse: %s",
                config.name,
                url,
                exc_info=True,
            )
            truncated = f"pagination stopped early: a later page failed to parse ({url})"
            break
        page_has_new = False
        page_added_unseen = False
        for job in page_jobs:
            if job.job_id not in all_jobs:
                page_added_unseen = True
            all_jobs[job.job_id] = job
            if known_ids is None or job.job_id not in known_ids:
                page_has_new = True
        next_url = scraper.next_page_url(payload, url)
        if next_url is None:
            break
        # A page whose every id was already collected earlier in this same run
        # means the board served a page it had already served. Some boards do
        # that instead of ending: Target's and Tempus's Workday tenants answer
        # any offset past the end with page 1 again, so the short page that
        # every other tenant uses to signal exhaustion never arrives and the run
        # paginates to the ceiling, where a seed is discarded as truncated.
        #
        # This is deliberately not conditioned on `known_ids` or on
        # `paginate_fully`. Both of those are about jobs seen on a *previous*
        # run, and say nothing about a board repeating itself inside one pass;
        # a page that adds no id this run cannot be a page of newer postings no
        # matter how the board is ordered.
        if page_jobs and not page_added_unseen:
            break
        if known_ids is not None and not page_has_new and not config.paginate_fully:
            stopped_on_known_page = True
            break
        url = next_url
    else:
        truncated = f"reached the {max_pages}-page pagination ceiling; more jobs may exist"
    return list(all_jobs.values()), truncated, stopped_on_known_page
