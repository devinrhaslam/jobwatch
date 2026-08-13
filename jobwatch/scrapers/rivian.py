from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Rivian's board is iCIMS underneath — every record's apply_url points at
# `us-careers-rivian.icims.com` — but its careers site fronts that with its own
# JSON API, which is the better source: one host, no iCIMS session, and it
# accepts both a real page size and a date sort, neither of which the iCIMS
# search page offers.
HOST = "https://careers.rivian.com"
API_URL = f"{HOST}/api/jobs"

# Unlike most boards here, this one honours a page size. 630 postings at 100 a
# page is seven requests.
PAGE_SIZE = 100
MAX_PAGES = 40

# `descending=true` on posted_date genuinely orders the board newest-first
# (verified against the first page), so the engine's early stop applies and a
# routine run reads one page.
QUERY = {
    "sortBy": "posted_date",
    "descending": "true",
    "internal": "false",
    "limit": PAGE_SIZE,
}

# The public posting page. `apply_url` is not a substitute: it jumps to the
# iCIMS login (`/jobs/<id>/login`) rather than showing the description.
POSTING_URL = f"{HOST}/careers-home/jobs/{{job_id}}"


def _page_url(page: int) -> str:
    return f"{API_URL}?{urlencode({**QUERY, 'page': page})}"


def _location(record: dict) -> str | None:
    full = record.get("full_location")
    if full:
        return str(full)
    parts = [record.get("city"), record.get("state"), record.get("country")]
    names = [str(p) for p in parts if p]
    return ", ".join(dict.fromkeys(names)) or None


def _posted_date(record: dict) -> str | None:
    """`posted_date` is a real publication timestamp, distinct from the
    `update_date` sitting next to it, which moves whenever a posting is
    edited."""
    raw = record.get("posted_date")
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), "%Y-%m-%dT%H:%M:%S%z").date().isoformat()
    except ValueError:
        return None


class RivianScraper(Scraper):
    """Rivian's careers board, read through the JSON API its careers app calls.

    Records arrive wrapped: the response is `{"jobs": [{"data": {...}}]}`, so
    each posting sits one level down under `data`.
    """

    config = CompanyConfig(
        name="Rivian",
        career_url=_page_url(1),
        fetch_mode=FetchMode.STATIC,
        max_pages=MAX_PAGES,
    )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("jobs") or []
        jobs: list[Job] = []
        for wrapper in records:
            record = wrapper.get("data") if isinstance(wrapper, dict) else None
            if not isinstance(record, dict):
                continue
            job_id = record.get("req_id") or record.get("slug")
            title = record.get("title")
            if not (job_id and title):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=POSTING_URL.format(job_id=job_id),
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        body = json.loads(payload)
        if len(body.get("jobs") or []) < PAGE_SIZE:
            return None  # a short page means the board is exhausted
        page = int(parse_qs(urlsplit(current_url).query).get("page", ["1"])[0])
        total = int(body.get("totalCount") or 0)
        if total and page * PAGE_SIZE >= total:
            return None
        return _page_url(page + 1)
