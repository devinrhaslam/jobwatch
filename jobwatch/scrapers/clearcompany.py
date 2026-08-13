from __future__ import annotations

import json
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# ClearCompany's public careers API, keyed by a company uuid. The company's own
# careers page calls this exact URL; careers-api.clearcompany.com serves an
# empty robots.txt.
API_URL = "https://careers-api.clearcompany.com/v1/{company_uuid}?pageIndex=0&pageSize={size}&source=CJB-0"

PAGE_SIZE = 100

# company -> (company uuid, template for the posting URL taking {job_id}).
#
# The posting URL is deliberately the company's own page rather than the
# ClearCompany portal the `applyLink` points at: that portal
# (<company>.clearcompany.com) answers `Disallow: /`, and its pages are empty
# shells to a plain fetch anyway. Firefly's own `?jobId=` page renders the
# posting — title, description and apply button — when loaded in a browser,
# which was checked rather than assumed.
BOARDS = {
    "Firefly Aerospace": (
        "00ed92c3-5bfb-7bfb-456d-4d9d77fef9a5",
        "https://fireflyspace.com/careers/?jobId={job_id}",
    ),
}


def _location(record: dict) -> str | None:
    """Every place the posting lists, built from the structured entries.

    The flat `location` string carries only the first one, so a role open in
    several cities would lose the rest.
    """
    names: list[str] = []
    remote = False
    for place in record.get("locations") or []:
        if not isinstance(place, dict):
            continue
        if place.get("isRemote"):
            remote = True
        parts = [
            str(place[key])
            for key in ("city", "subdivision", "country")
            if place.get(key)
        ]
        name = ", ".join(parts)
        if name and name not in names:
            names.append(name)
    if not names:
        flat = record.get("location")
        if flat:
            names.append(str(flat).strip())
    place = "; ".join(names)
    if remote:
        return f"{place} (Remote)" if place else "Remote"
    return place or None


def _posted_date(record: dict) -> str | None:
    """`postedDate` is a real publication date — 52 distinct values across
    Firefly's board, spanning nine months rather than clustering at the fetch."""
    raw = record.get("postedDate") or record.get("openDate")
    if not raw:
        return None
    text = str(raw)[:10]
    return text if len(text) == 10 and text.count("-") == 2 else None


class ClearCompanyScraper(Scraper):
    """One parameterised scraper for companies on a public ClearCompany board."""

    def __init__(self, company: str, company_uuid: str, posting_url: str):
        self.company_uuid = company_uuid
        self.posting_url = posting_url
        self.config = CompanyConfig(
            name=company,
            career_url=API_URL.format(company_uuid=company_uuid, size=PAGE_SIZE),
            fetch_mode=FetchMode.STATIC,
        )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("results") or []
        jobs: list[Job] = []
        for record in records:
            job_id = record.get("id")
            title = record.get("positionTitle")
            if not (job_id and title):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=self.posting_url.format(job_id=job_id),
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        data = json.loads(payload)
        results = data.get("results") or []
        if not results:
            return None
        parsed = urlsplit(current_url)
        params = parse_qs(parsed.query)
        index = int(params.get("pageIndex", ["0"])[0])
        # `totalCount` is the whole board, so it says directly whether another
        # page exists rather than needing a short page to infer it.
        seen = (index + 1) * PAGE_SIZE
        if seen >= int(data.get("totalCount") or 0):
            return None
        params["pageIndex"] = [str(index + 1)]
        return urlunsplit(parsed._replace(query=urlencode(params, doseq=True)))


def scrapers() -> list[ClearCompanyScraper]:
    return [
        ClearCompanyScraper(company, uuid, posting_url)
        for company, (uuid, posting_url) in BOARDS.items()
    ]
