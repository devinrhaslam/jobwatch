from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

API_PATH = "/api/apply/v2/jobs"

# The board ignores a larger `num`, always answering with ten postings.
PAGE_SIZE = 10

# Enough pages to read the largest board here in full (Netflix, ~481 postings)
# with room to grow.
MAX_PAGES = 120

# company -> (host, domain). The host is the company's own careers domain, which
# proxies its Eightfold tenant; `domain` selects the tenant.
#
# Microsoft is deliberately absent. Its careers site is Eightfold-backed, but the
# tenant answers 403 {"message": "Not authorized for PCSX"} to the public jobs
# API on every host and header combination tried, so it needs its own recon
# rather than a BOARDS entry.
BOARDS = {
    "Netflix": ("https://explore.jobs.netflix.net", "netflix.com"),
}


def _page_url(host: str, domain: str, start: int) -> str:
    query = urlencode(
        {"domain": domain, "start": start, "num": PAGE_SIZE, "sort_by": "timestamp"}
    )
    return f"{host}{API_PATH}?{query}"


def _location(record: dict) -> str | None:
    locations = record.get("locations")
    if isinstance(locations, list):
        names = [str(item) for item in locations if item]
        if names:
            return ", ".join(dict.fromkeys(names))
    single = record.get("location")
    return str(single) if single else None


def _posted_date(record: dict) -> str | None:
    """`t_create` is a real Unix timestamp, so unlike Workday the date is exact.
    `t_update` is not a substitute: it moves whenever a posting is edited."""
    raw = record.get("t_create")
    if not raw:
        return None
    try:
        return datetime.fromtimestamp(int(raw), timezone.utc).date().isoformat()
    except (ValueError, OSError, OverflowError):
        return None


class EightfoldScraper(Scraper):
    """One parameterised scraper for companies on an Eightfold-hosted board.

    Unlike Greenhouse, Ashby, and Workday, this board is **not ordered by
    recency**, despite accepting a `sort_by=timestamp` parameter. Measured
    against Netflix's 481 postings, the fifteen most recently created were
    spread across pages 1 to 22 of 49 — the response is two independently
    sorted blocks concatenated. The engine's no-new-ids early stop assumes
    newest-first ordering, so this config sets paginate_fully and reads every
    page on every run. Skipping that would silently drop new postings that
    happen to land in the second block.
    """

    def __init__(self, company: str, host: str, domain: str):
        self.host = host
        self.domain = domain
        self.config = CompanyConfig(
            name=company,
            career_url=_page_url(host, domain, 0),
            fetch_mode=FetchMode.STATIC,
            max_pages=MAX_PAGES,
            paginate_fully=True,
        )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("positions") or []
        jobs: list[Job] = []
        for record in records:
            job_id = record.get("id") or record.get("display_job_id")
            title = record.get("name")
            url = record.get("canonicalPositionUrl")
            if not (job_id and title and url):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=title.strip(),
                    url=url,
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        records = json.loads(payload).get("positions") or []
        if len(records) < PAGE_SIZE:
            return None  # a short page means the board is exhausted
        parsed = urlsplit(current_url)
        params = parse_qs(parsed.query)
        start = int(params.get("start", ["0"])[0]) + PAGE_SIZE
        params["start"] = [str(start)]
        query = urlencode({key: value[0] for key, value in params.items()})
        return urlunsplit(parsed._replace(query=query))


def scrapers() -> list[EightfoldScraper]:
    return [EightfoldScraper(company, host, domain) for company, (host, domain) in BOARDS.items()]
