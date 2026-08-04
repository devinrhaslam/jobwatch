from __future__ import annotations

import json
from datetime import datetime

from jobwatch.fetch import build_post_url, split_post_url
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

API_URL = "https://www.uber.com/api/loadSearchJobsResults?localeCode=en"
POSTING_URL = "https://www.uber.com/careers/list/{job_id}/"

MAX_PAGES = 30

# The endpoint answers 403 without an x-csrf-token header, but accepts any
# value — it is a bot filter, not authentication, so no token is fetched or
# stored. Sending a placeholder is enough.
REQUEST_HEADERS = {"x-csrf-token": "jobwatch"}


def _body(page: int) -> dict:
    """Deliberately omits `limit`.

    Supplied, it is honoured exactly (limit=100 returns 100 of 649). Omitted,
    the endpoint answers the whole board in one request, which is both fewer
    requests and immune to a page-boundary bug.

    `page` belongs at the top level. Nesting it under `params`, or using
    `offset`/`start`, is accepted and silently ignored — every page then
    returns the same first results, which looks like working pagination.
    """
    return {"params": {}, "page": page}


def _location(record: dict) -> str | None:
    places = record.get("allLocations") or []
    if not places and record.get("location"):
        places = [record["location"]]
    names = []
    for place in places:
        if not isinstance(place, dict):
            continue
        parts = [place.get("city"), place.get("region"), place.get("countryName")]
        name = ", ".join(str(p) for p in parts if p)
        if name and name not in names:
            names.append(name)
    return " | ".join(names) or None


def _posted_date(record: dict) -> str | None:
    raw = record.get("creationDate")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


class UberScraper(Scraper):
    """Uber's own careers search API.

    A POST-only JSON endpoint, so it uses FetchMode.JSON_POST with the request
    body carried in the page URL. Postings carry a real `creationDate`, so
    posted_date is exact.
    """

    config = CompanyConfig(
        name="Uber",
        career_url=build_post_url(API_URL, _body(0)),
        fetch_mode=FetchMode.JSON_POST,
        max_pages=MAX_PAGES,
        request_headers=REQUEST_HEADERS,
    )

    def parse(self, payload: str) -> list[Job]:
        data = json.loads(payload).get("data") or {}
        records = data.get("results") or []
        jobs: list[Job] = []
        for record in records:
            job_id = record.get("id")
            title = record.get("title")
            if not (job_id and title):
                continue
            jobs.append(
                Job(
                    company="Uber",
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=POSTING_URL.format(job_id=job_id),
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        """One request normally covers the board, so this is a safety net: it
        only asks for another page if the response returned fewer postings than
        it says exist, which would mean the endpoint started capping."""
        data = json.loads(payload).get("data") or {}
        returned = len(data.get("results") or [])
        total = (data.get("totalResults") or {}).get("low")
        if not returned or not isinstance(total, int) or returned >= total:
            return None
        endpoint, body = split_post_url(current_url)
        return build_post_url(endpoint, _body(int(body.get("page", 0)) + 1))
