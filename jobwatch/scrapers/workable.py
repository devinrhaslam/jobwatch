from __future__ import annotations

import json

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Workable's public widget account endpoint. It answers the whole board in one
# request — there is no offset or page parameter, and none of the accounts here
# is near a size where that would matter. robots.txt on apply.workable.com is
# an empty `Disallow:`, which allows everything.
API_URL = "https://apply.workable.com/api/v1/widget/accounts/{slug}"

# company -> account slug.
BOARDS = {
    "Hugging Face": "huggingface",
}


def _location(record: dict) -> str | None:
    """Build a place from the parts, because the record's own `location` field
    is null on every posting seen — the city, state and country are separate
    keys and only those are populated."""
    parts = [
        str(record.get(key)).strip()
        for key in ("city", "state", "country")
        if record.get(key)
    ]
    place = ", ".join(dict.fromkeys(parts))
    if record.get("telecommuting"):
        return f"{place} (Remote)" if place else "Remote"
    return place or None


def _posted_date(record: dict) -> str | None:
    """`published_on` is already a plain YYYY-MM-DD publication date, unlike the
    `created_at` timestamp beside it, which moves when a posting is edited."""
    raw = record.get("published_on")
    if not raw:
        return None
    text = str(raw)[:10]
    return text if len(text) == 10 and text.count("-") == 2 else None


class WorkableScraper(Scraper):
    """One parameterised scraper for every company on a public Workable board.

    The posting URL comes from the record rather than being built from the
    shortcode: `url` is the posting page and `application_url` is the same page's
    apply form, so the posting is preferred for the same reason as on Lever — a
    reported link should open the description.
    """

    def __init__(self, company: str, slug: str):
        self.slug = slug
        self.config = CompanyConfig(
            name=company,
            career_url=API_URL.format(slug=slug),
            fetch_mode=FetchMode.STATIC,
        )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("jobs") or []
        jobs: list[Job] = []
        for record in records:
            job_id = record.get("shortcode")
            title = record.get("title")
            url = record.get("url") or record.get("application_url")
            if not (job_id and title and url):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=str(url),
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs


def scrapers() -> list[WorkableScraper]:
    return [WorkableScraper(company, slug) for company, slug in BOARDS.items()]
