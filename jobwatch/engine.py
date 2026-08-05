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
) -> CompanyResult:
    config = scraper.config
    is_seed_run = not state.snapshot_exists(config.name, state_dir)
    snapshot = state.load_snapshot(config.name, state_dir)

    try:
        jobs, truncation_detail = _fetch_all_pages(
            scraper,
            config,
            known_ids=None if is_seed_run else set(snapshot),
            fetch_page=fetch_page,
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

    # An empty snapshot is deliberately exempt: this guard detects a site
    # changing its job ID scheme, which is only knowable by comparison against
    # jobs already recorded. With nothing recorded, an all-new run is expected
    # (a company that had no openings when it was first seeded), so flagging it
    # would be a false alarm that withholds genuinely new jobs.
    if (
        snapshot
        and jobs
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


def _fetch_all_pages(
    scraper: Scraper,
    config: CompanyConfig,
    *,
    known_ids: set[str] | None,
    fetch_page: FetchPage,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[Job], str | None]:
    all_jobs: dict[str, Job] = {}
    url = config.career_url
    truncated: str | None = None
    max_pages = config.max_pages or MAX_PAGES
    page_delay = (
        config.inter_page_delay_seconds
        if config.inter_page_delay_seconds is not None
        else INTER_PAGE_DELAY_SECONDS
    )
    for page_number in range(max_pages):
        if page_number:
            sleep(page_delay)
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
        for job in page_jobs:
            all_jobs[job.job_id] = job
            if known_ids is None or job.job_id not in known_ids:
                page_has_new = True
        next_url = scraper.next_page_url(payload, url)
        if next_url is None:
            break
        if known_ids is not None and not page_has_new and not config.paginate_fully:
            break
        url = next_url
    else:
        truncated = f"reached the {max_pages}-page pagination ceiling; more jobs may exist"
    return list(all_jobs.values()), truncated
