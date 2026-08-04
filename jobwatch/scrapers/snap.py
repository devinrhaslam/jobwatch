from __future__ import annotations

import json

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

API_URL = "https://careers.snap.com/api/jobs"


def _location(source: dict) -> str | None:
    offices = source.get("offices")
    if isinstance(offices, list):
        names = [
            str(office.get("location") or office.get("name"))
            for office in offices
            if isinstance(office, dict) and (office.get("location") or office.get("name"))
        ]
        if names:
            return ", ".join(dict.fromkeys(names))
    primary = source.get("primary_location")
    return str(primary) if primary else None


class SnapScraper(Scraper):
    """Snap's own careers search API.

    The board is Workday-backed — posting URLs point at myworkdaysite.com — but
    Snap fronts it with a search endpoint that answers the whole board in a
    single request, so this reads that rather than the Workday CXS API.

    The response is Elasticsearch-shaped: each hit wraps the posting in
    `_source`. Postings carry no publication timestamp, so recency comes purely
    from snapshot diffing, as with Meta.
    """

    config = CompanyConfig(
        name="Snap",
        career_url=API_URL,
        fetch_mode=FetchMode.STATIC,
    )

    def parse(self, payload: str) -> list[Job]:
        hits = json.loads(payload).get("body") or []
        jobs: list[Job] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            source = hit.get("_source") or {}
            job_id = source.get("id") or hit.get("_id")
            title = source.get("title")
            url = source.get("absolute_url")
            if not (job_id and title and url):
                continue
            jobs.append(
                Job(
                    company="Snap",
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=url,
                    location=_location(source),
                )
            )
        return jobs
