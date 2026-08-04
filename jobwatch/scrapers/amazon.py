from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

BASE = "https://www.amazon.jobs"
API_URL = f"{BASE}/en/search.json"

PAGE_SIZE = 100
MAX_PAGES = 40

# Amazon's board runs to tens of thousands of postings across every function,
# so the entry URL narrows at source — the same approach Meta's scraper takes,
# and for the same reason: enumerating everything would be impractical and
# almost entirely irrelevant. sort=recent is what makes the engine's early stop
# safe here, so a routine run reads one page.
QUERY = {
    "base_query": "software engineer",
    "sort": "recent",
    "result_limit": PAGE_SIZE,
    "offset": 0,
}

# "August  4, 2026" — note the doubled space for single-digit days.
_POSTED = re.compile(r"^\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s*$")


def _posted_date(record: dict) -> str | None:
    match = _POSTED.match(record.get("posted_date") or "")
    if not match:
        return None
    month, day, year = match.groups()
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(f"{month} {day} {year}", fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _location(record: dict) -> str | None:
    return record.get("normalized_location") or record.get("location") or None


class AmazonScraper(Scraper):
    """Amazon's own careers search API.

    Not a shared platform parser: amazon.jobs is a bespoke portal. The response
    is plain JSON though, so no browser is needed.
    """

    config = CompanyConfig(
        name="Amazon",
        career_url=f"{API_URL}?{urlencode(QUERY)}",
        fetch_mode=FetchMode.STATIC,
        max_pages=MAX_PAGES,
    )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("jobs") or []
        jobs: list[Job] = []
        for record in records:
            job_id = record.get("id_icims") or record.get("id")
            title = record.get("title")
            path = record.get("job_path")
            if not (job_id and title and path):
                continue
            jobs.append(
                Job(
                    company="Amazon",
                    job_id=str(job_id),
                    title=title.strip(),
                    url=f"{BASE}{path}" if path.startswith("/") else path,
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        data = json.loads(payload)
        records = data.get("jobs") or []
        if len(records) < PAGE_SIZE:
            return None
        parsed = urlsplit(current_url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        offset = int(params.get("offset", 0)) + PAGE_SIZE
        if offset >= int(data.get("hits") or 0):
            return None
        params["offset"] = str(offset)
        return urlunsplit(parsed._replace(query=urlencode(params)))
