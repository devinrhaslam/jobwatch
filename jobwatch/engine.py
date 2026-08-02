from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from jobwatch import diff, state
from jobwatch.fetch import FetchBlocked, FetchError, fetch_rendered, fetch_static
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

MAX_PAGES = 20
SUSPICIOUS_NEW_JOB_RATIO = 0.8
logger = logging.getLogger(__name__)

FetchPage = Callable[[CompanyConfig, str], str]


def default_fetch_page(config: CompanyConfig, url: str, *, browser=None) -> str:
    if config.fetch_mode is FetchMode.STATIC:
        return fetch_static(url)
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
        jobs = _fetch_all_pages(
            scraper,
            config,
            known_ids=None if is_seed_run else set(snapshot),
            fetch_page=fetch_page,
        )
    except FetchBlocked as exc:
        return CompanyResult(config.name, "blocked", [], 0, str(exc))
    except FetchError as exc:
        return CompanyResult(config.name, "failed", [], 0, str(exc))

    if not jobs and snapshot:
        return CompanyResult(
            config.name,
            "failed",
            [],
            0,
            "parser returned zero jobs against a non-empty snapshot",
        )

    new_jobs = diff.find_new_jobs(jobs, snapshot)

    # An empty snapshot is deliberately exempt: this guard detects a site
    # changing its job ID scheme, which is only knowable by comparison against
    # jobs already recorded. With nothing recorded, an all-new run is expected
    # (a company that had no openings when it was first seeded), so flagging it
    # would be a false alarm that withholds genuinely new jobs.
    if snapshot and jobs and len(new_jobs) / len(jobs) >= SUSPICIOUS_NEW_JOB_RATIO:
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
    return CompanyResult(config.name, status, reported_new, len(jobs))


def _fetch_all_pages(
    scraper: Scraper,
    config: CompanyConfig,
    *,
    known_ids: set[str] | None,
    fetch_page: FetchPage,
) -> list[Job]:
    all_jobs: dict[str, Job] = {}
    url = config.career_url
    for _ in range(MAX_PAGES):
        try:
            payload = fetch_page(config, url)
            page_jobs = scraper.parse(payload)
        except (FetchBlocked, FetchError):
            if not all_jobs:
                raise
            logger.warning(
                "Stopping pagination for %s after a later page failed: %s",
                config.name,
                url,
                exc_info=True,
            )
            break
        page_has_new = False
        for job in page_jobs:
            all_jobs[job.job_id] = job
            if known_ids is None or job.job_id not in known_ids:
                page_has_new = True
        next_url = scraper.next_page_url(payload, url)
        if next_url is None:
            break
        if known_ids is not None and not page_has_new:
            break
        url = next_url
    return list(all_jobs.values())
