from __future__ import annotations

import json

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Comeet's public careers API, which answers a whole board in one response.
# Note the host is comeet.co, not the comeet.com that serves the human-facing
# board; robots.txt there disallows only `*?s=*`.
API_URL = "https://www.comeet.co/careers-api/2.0/company/{company_uid}/positions?token={token}"

# company -> (company uid, token).
#
# The token is not a credential. It ships in the client payload of the
# company's own careers page — vastdata.com/careers embeds this exact URL — and
# identifies which public board to serve, the way a Greenhouse slug does. It
# will change if the company rotates its board, which shows up as a failed run
# rather than as silently wrong data.
BOARDS = {
    "VAST Data": ("43.001", "34110453411D4968234168209C31D49"),
}


def _location(record: dict) -> str | None:
    location = record.get("location") or {}
    name = location.get("name")
    if name:
        return str(name).strip()
    parts = [str(location[key]) for key in ("city", "state", "country") if location.get(key)]
    return ", ".join(parts) or None


class ComeetScraper(Scraper):
    """One parameterised scraper for companies on a public Comeet board.

    The board's own page (comeet.com/jobs/<company>/<uid>) renders client-side
    and carries no postings in its HTML, so this reads the API that page calls.

    No posted_date: the only timestamp is `time_updated`, which is a
    modification time — the same reason the Greenhouse scraper refuses
    `updated_at`.
    """

    def __init__(self, company: str, company_uid: str, token: str):
        self.company_uid = company_uid
        self.config = CompanyConfig(
            name=company,
            career_url=API_URL.format(company_uid=company_uid, token=token),
            fetch_mode=FetchMode.STATIC,
        )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload)
        if not isinstance(records, list):
            return []
        jobs: list[Job] = []
        for record in records:
            # Internal-only postings are not openings a candidate can apply to.
            if record.get("is_internal"):
                continue
            job_id = record.get("uid")
            title = record.get("name")
            url = record.get("url_active_page") or record.get("url_comeet_hosted_page")
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


def scrapers() -> list[ComeetScraper]:
    return [
        ComeetScraper(company, company_uid, token)
        for company, (company_uid, token) in BOARDS.items()
    ]
