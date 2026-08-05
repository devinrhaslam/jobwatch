from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Microsoft's careers site is served by Eightfold's PCSX product, but not on the
# Eightfold tenant host the other Eightfold company (Netflix) uses. The tenant
# API answers `403 {"message": "Not authorized for PCSX"}` — the message names
# the product that *does* serve this board, on Microsoft's own apply host, which
# needs no key, no CSRF token, and no browser.
HOST = "https://apply.careers.microsoft.com"
API_URL = f"{HOST}/api/pcsx/search"
DOMAIN = "microsoft.com"

# The API returns 10 results per page and ignores every page-size parameter
# tried (num, pageSize, size, limit, rows, pgSz, count, n), so seeding the board
# costs ~185 requests and about two minutes. Results come newest-first by
# default (`sortBy: timestamp`), so the engine's early stop keeps a routine run
# down to a page or two.
PAGE_SIZE = 10
MAX_PAGES = 220
# This board does answer 429 during a seed, but the cause turned out to be
# connection churn rather than request rate — the fix was the shared session in
# fetch.py, and slowing down alone did not help (a seed died at page 33 of 185
# even at one second per page). This slightly longer pause is kept only as
# margin on a board known to rate-limit; only the seed pays for it, since a
# routine run stops after a page or two.
INTER_PAGE_DELAY_SECONDS = 1.0


def _page_url(start: int) -> str:
    query = urlencode(
        {"domain": DOMAIN, "query": "", "location": "", "start": start}
    )
    return f"{API_URL}?{query}"


def _data(payload: str) -> dict:
    body = json.loads(payload)
    return body.get("data") or {}


def _location(record: dict) -> str | None:
    names = [str(name) for name in (record.get("locations") or []) if name]
    return ", ".join(dict.fromkeys(names)) or None


def _posted_date(record: dict) -> str | None:
    raw = record.get("postedTs")
    if not raw:
        return None
    try:
        return datetime.fromtimestamp(int(raw), timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _posting_url(record: dict) -> str | None:
    """Prefer the link the API hands out over one built from an id.

    `positionUrl` is site-relative (`/careers/job/<id>`) and resolves directly;
    the jobs.careers.microsoft.com form for the same posting only redirects here.
    """
    path = record.get("positionUrl")
    if path:
        return f"{HOST}{path}" if str(path).startswith("/") else str(path)
    position_id = record.get("id")
    return f"{HOST}/careers/job/{position_id}" if position_id else None


class MicrosoftScraper(Scraper):
    """Microsoft's careers board, read through the PCSX search API.

    Jobs are keyed on `displayJobId` — the requisition number shown on the
    posting — rather than the `id` in the URL, because the requisition survives
    a re-index of the portal's internal ids while still being unique (verified
    across all 1,849 current postings).
    """

    config = CompanyConfig(
        name="Microsoft",
        career_url=_page_url(0),
        fetch_mode=FetchMode.STATIC,
        max_pages=MAX_PAGES,
        inter_page_delay_seconds=INTER_PAGE_DELAY_SECONDS,
    )

    def parse(self, payload: str) -> list[Job]:
        jobs: list[Job] = []
        for record in _data(payload).get("positions") or []:
            if not isinstance(record, dict):
                continue
            job_id = record.get("displayJobId") or record.get("id")
            title = record.get("name")
            url = _posting_url(record)
            if not (job_id and title and url):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=url,
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        data = _data(payload)
        if len(data.get("positions") or []) < PAGE_SIZE:
            return None  # a short page means the board is exhausted
        start = int(parse_qs(urlsplit(current_url).query).get("start", ["0"])[0])
        start += PAGE_SIZE
        total = int(data.get("count") or 0)
        if total and start >= total:
            return None
        return _page_url(start)
