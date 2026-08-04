from __future__ import annotations

import json
import re

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Tesla's careers page is a client-rendered app in front of one API call that
# returns the entire board — every listing, plus the lookup tables that decode
# it — in a single response. Reading that call gives the whole board in one
# request and does not depend on the page's markup.
STATE_API = "/cua-api/apps/careers/state"
CAREERS_URL = "https://www.tesla.com/careers/search/"
POSTING_URL = "https://www.tesla.com/careers/search/job/{slug}-{job_id}"

# www.tesla.com sits behind Akamai Bot Manager, which answers plain HTTP — and
# headless Chromium — with "Access Denied" before any request reaches the board.
# Headless Firefox is served the page normally, so this reads the site with an
# ordinary browser rather than by disguising one.
BROWSER_ENGINE = "firefox"


def _slug(title: str) -> str:
    """Reproduce the readable prefix Tesla puts in its own job links.

    The prefix is decorative: the router keys on the trailing id, and a link
    whose slug is wrong still resolves to the right posting. So this exists to
    make a reported link readable, and cannot produce a dead one.
    """
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


class TeslaScraper(Scraper):
    """Tesla's careers board, read through the state API its own page consumes.

    Listings are stored in a compact form — `t` title, `l` location id, `id`
    requisition — with the human-readable names held once in a `lookup` table
    rather than repeated across ~7,500 rows.

    Postings carry no publication date (`pu`, where present, is an expiry), so
    recency comes from snapshot diffing.
    """

    config = CompanyConfig(
        name="Tesla",
        career_url=CAREERS_URL,
        fetch_mode=FetchMode.RENDERED_XHR,
        capture_response_url=STATE_API,
        browser_engine=BROWSER_ENGINE,
        max_pages=1,  # one response carries the entire board
    )

    def parse(self, payload: str) -> list[Job]:
        state = json.loads(payload)
        locations = (state.get("lookup") or {}).get("locations") or {}
        jobs: list[Job] = []
        for record in state.get("listings") or []:
            if not isinstance(record, dict):
                continue
            job_id = record.get("id")
            title = record.get("t")
            if not (job_id and title):
                continue
            title = str(title).strip()
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=title,
                    url=POSTING_URL.format(slug=_slug(title), job_id=job_id),
                    location=locations.get(str(record.get("l"))),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        return None  # the board arrives whole; there is nothing to paginate
