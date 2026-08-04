from __future__ import annotations

import json
from datetime import datetime

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

# Companies whose public job board is hosted by Ashby, keyed by company name ->
# board slug. Verified live by tools/probe_ats.py.
#
# Note the endpoint rejects a default urllib User-Agent with 403; fetch_static
# already sends a realistic one, so this only bites ad-hoc scripts.
BOARDS = {
    "Linear": "linear",
    "Notion": "notion",
    "OpenAI": "openai",
    "Plaid": "plaid",
    "Ramp": "ramp",
    "Snowflake": "snowflake",
}


def _location(record: dict) -> str | None:
    """Primary location plus any secondary ones, matching how Greenhouse boards
    present multi-site roles."""
    names = []
    primary = record.get("location")
    if primary:
        names.append(str(primary))
    for entry in record.get("secondaryLocations") or []:
        name = entry.get("location") if isinstance(entry, dict) else None
        if name and str(name) not in names:
            names.append(str(name))
    return ", ".join(names) or None


def _posted_date(record: dict) -> str | None:
    raw = record.get("publishedAt")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        return None


class AshbyScraper(Scraper):
    """One parameterised scraper for every company on a public Ashby board.

    Same reasoning as the Greenhouse scraper: Ashby is the ATS recruiters post
    into, so its posting API is the upstream source rather than a mirror, and it
    carries a real `publishedAt` timestamp.
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
            # isListed is the board's own published flag. Every job on the
            # boards sampled so far is listed, but an unlisted posting is not
            # public and should not be reported as something to apply to.
            if record.get("isListed") is False:
                continue
            job_id = record.get("id")
            title = record.get("title")
            url = record.get("jobUrl") or record.get("applyUrl")
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


def scrapers() -> list[AshbyScraper]:
    return [AshbyScraper(company, slug) for company, slug in BOARDS.items()]
