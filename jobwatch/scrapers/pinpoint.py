from __future__ import annotations

import json

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Pinpoint's public postings feed. It answers the whole board in one request and
# robots.txt on the tenant disallows only /mydata, /admin and /companies.
API_URL = "https://{tenant}.pinpointhq.com/postings.json"

# company -> Pinpoint tenant.
BOARDS = {
    "Impulse Space": "impulsespace",
}


def _location(record: dict) -> str | None:
    """City and province from the location object.

    `name` is the display field but arrives padded ("Redondo Beach "), and it
    omits the province, so the parts are assembled and the name is the fallback.
    """
    location = record.get("location") or {}
    parts = [
        str(location[key]).strip()
        for key in ("city", "province", "country")
        if location.get(key)
    ]
    if parts:
        return ", ".join(dict.fromkeys(parts))
    name = location.get("name")
    return str(name).strip() if name else None


class PinpointScraper(Scraper):
    """One parameterised scraper for companies on a public Pinpoint board.

    No posted_date: the feed carries `deadline_at` but no publication field at
    all — `published_at` is absent from every record — so recency comes from
    snapshot diffing.
    """

    def __init__(self, company: str, tenant: str):
        self.tenant = tenant
        self.config = CompanyConfig(
            name=company,
            career_url=API_URL.format(tenant=tenant),
            fetch_mode=FetchMode.STATIC,
        )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("data") or []
        jobs: list[Job] = []
        for record in records:
            job_id = record.get("id")
            title = record.get("title")
            url = record.get("url")
            if not (job_id and title and url):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=str(url),
                    location=_location(record),
                    posted_date=None,
                )
            )
        return jobs


def scrapers() -> list[PinpointScraper]:
    return [PinpointScraper(company, tenant) for company, tenant in BOARDS.items()]
