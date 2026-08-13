from __future__ import annotations

import json

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# The endpoint wayfair.com/careers/jobs renders from. It answers the entire
# board in one response — no paging parameters, ~380 postings, several MB — and
# robots.txt disallows a list of specific /a/ paths that does not include this
# one.
API_URL = "https://www.wayfair.com/a/careers/careers/job_search_data"

# Without this the same URL serves the careers page's HTML instead of its data.
# No other header, cookie or token is needed.
REQUEST_HEADERS = {"Accept": "application/json"}


def _location(record: dict) -> str | None:
    """The location object's display name, which already reads "City, ST".

    Falls back to assembling one, because the name is the only field guaranteed
    to be formatted and the parts are occasionally the more complete pair.
    """
    location = record.get("location") or {}
    name = location.get("name")
    if name:
        return str(name).strip()
    parts = [str(location[key]) for key in ("city", "state", "country") if location.get(key)]
    return ", ".join(parts) or None


def _posted_date(record: dict) -> str | None:
    """`createdDate` is a real publication date, unlike the index timestamps
    other own-hosted boards expose: 317 distinct values across 380 postings,
    spanning ten months rather than clustering at the moment of the fetch."""
    raw = record.get("createdDate")
    if not raw:
        return None
    text = str(raw)[:10]
    return text if len(text) == 10 and text.count("-") == 2 else None


class WayfairScraper(Scraper):
    """Wayfair's careers board, read from the endpoint its own page calls.

    job_id is the requisition id rather than the internal row id, because it is
    the one that appears in the posting URL (`?folderId=`), which keeps a
    snapshot entry traceable to the listing it came from.

    The postings live on Wayfair's Avature portal, but that host publishes no
    sitemap of them — only an event listing — so the Avature scraper cannot
    reach this board and it is read here instead.
    """

    config = CompanyConfig(
        name="Wayfair",
        career_url=API_URL,
        fetch_mode=FetchMode.STATIC,
        request_headers=REQUEST_HEADERS,
    )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("jobListData") or []
        jobs: list[Job] = []
        for record in records:
            # Every posting seen is active and publicly listed, but the board
            # carries the flags to say otherwise, so honour them rather than
            # reporting a hidden or referral-only role as an opening.
            if record.get("isHidden") or record.get("isReferralOnly"):
                continue
            if record.get("isActive") is False:
                continue
            job_id = record.get("requisitionId") or record.get("eid") or record.get("id")
            title = record.get("title")
            url = record.get("applyLink") or record.get("structuredDataApplyLink")
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
