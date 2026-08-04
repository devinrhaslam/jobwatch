from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

API_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
POSTING_URL = "https://jobs.smartrecruiters.com/{identifier}/{job_id}"

PAGE_SIZE = 100
MAX_PAGES = 60

# company -> board slug. Verified live by tools/probe_ats.py.
BOARDS = {
    "Canva": "canva",
}


def _location(record: dict) -> str | None:
    location = record.get("location") or {}
    full = location.get("fullLocation")
    if full:
        # "Sydney, , Australia" — the API leaves the region segment empty.
        parts = [part.strip() for part in str(full).split(",") if part.strip()]
        if parts:
            return ", ".join(parts)
    city = location.get("city")
    country = location.get("country")
    parts = [str(p) for p in (city, country) if p]
    if location.get("remote"):
        parts.append("Remote")
    return ", ".join(parts) or None


def _posted_date(record: dict) -> str | None:
    raw = record.get("releasedDate") or record.get("createdOn")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


class SmartRecruitersScraper(Scraper):
    """One parameterised scraper for companies on a public SmartRecruiters board.

    Postings carry `releasedDate`, so posted_date is exact. The API returns no
    posting URL, so it is built from the company identifier and job id — a shape
    verified to resolve.
    """

    def __init__(self, company: str, slug: str):
        self.slug = slug
        self.config = CompanyConfig(
            name=company,
            career_url=f"{API_URL.format(slug=slug)}?{urlencode({'limit': PAGE_SIZE, 'offset': 0})}",
            fetch_mode=FetchMode.STATIC,
            max_pages=MAX_PAGES,
        )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("content") or []
        jobs: list[Job] = []
        for record in records:
            job_id = record.get("id")
            title = record.get("name")
            identifier = (record.get("company") or {}).get("identifier")
            if not (job_id and title and identifier):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=title.strip(),
                    url=POSTING_URL.format(identifier=identifier, job_id=job_id),
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        data = json.loads(payload)
        records = data.get("content") or []
        if len(records) < PAGE_SIZE:
            return None
        parsed = urlsplit(current_url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        offset = int(params.get("offset", 0)) + PAGE_SIZE
        if offset >= int(data.get("totalFound") or 0):
            return None
        params["offset"] = str(offset)
        return urlunsplit(parsed._replace(query=urlencode(params)))


def scrapers() -> list[SmartRecruitersScraper]:
    return [SmartRecruitersScraper(company, slug) for company, slug in BOARDS.items()]
