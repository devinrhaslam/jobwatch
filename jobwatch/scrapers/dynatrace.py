from __future__ import annotations

import json
import re

from jobwatch.fetch import build_post_url, split_post_url
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# careers.dynatrace.com renders its listing from a Coveo index, reached through
# this proxy on Dynatrace's own domain. It needs no token and accepts a plain
# search body; robots.txt disallows a handful of paths and none of them is /api.
API_URL = "https://www.dynatrace.com/api/coveo/search/"

# The proxy honours a page size of 100, and `firstResult` is the offset.
PAGE_SIZE = 100

# Posting URLs are `/careers/jobs/<id>/`, and that id is the board's own key.
JOB_ID = re.compile(r"/careers/jobs/(\d+)")


def _body(offset: int) -> dict:
    return {"q": "", "numberOfResults": PAGE_SIZE, "firstResult": offset}


def _location(raw: dict) -> str | None:
    """Offices first, then countries, deduplicated in order.

    A role open in several offices lists each, and the country list is a
    separate field rather than part of the office name.
    """
    names: list[str] = []
    for key in ("office_locations", "country"):
        value = raw.get(key)
        if isinstance(value, str):
            value = [value]
        for entry in value or []:
            if entry and str(entry) not in names:
                names.append(str(entry))
    return ", ".join(names) or None


class DynatraceScraper(Scraper):
    """Dynatrace's careers listing, read from the Coveo proxy behind it.

    No posted_date. Every result carries a `date`, but across a whole page those
    values land within a few seconds of each other and move with each crawl —
    it is when the index last saw the posting, not when the posting appeared.
    Reporting it would be the same mistake as trusting Greenhouse's `updated_at`.
    """

    config = CompanyConfig(
        name="Dynatrace",
        career_url=build_post_url(API_URL, _body(0)),
        fetch_mode=FetchMode.JSON_POST,
    )

    def parse(self, payload: str) -> list[Job]:
        results = json.loads(payload).get("results") or []
        jobs: list[Job] = []
        for record in results:
            url = record.get("clickUri") or record.get("uri")
            title = record.get("title")
            if not (url and title):
                continue
            match = JOB_ID.search(url)
            if not match:
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=match.group(1),
                    title=str(title).strip(),
                    url=url,
                    location=_location(record.get("raw") or {}),
                    posted_date=None,
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        results = json.loads(payload).get("results") or []
        if len(results) < PAGE_SIZE:
            return None  # a short page means the index is exhausted
        endpoint, body = split_post_url(current_url)
        return build_post_url(endpoint, _body(int(body.get("firstResult", 0)) + PAGE_SIZE))
