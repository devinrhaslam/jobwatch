from __future__ import annotations

import json
import re

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# revolut.com answers 403 "Just a quick security check" to plain HTTP and to
# headless Chromium, but serves headless Firefox the page normally — the same
# engine-specific check Tesla turned out to have. This is not a bypass: it is a
# real browser engine asking for the page, with nothing spoofed.
LISTING_URL = "https://www.revolut.com/en-US/careers/"

BROWSER_ENGINE = "firefox"

# The whole board — 534 postings across fifteen teams — is in the page's
# __NEXT_DATA__, even though only six render before "Show more". The team pages
# and the `_next/data/<buildId>/…json` endpoint each hold a subset and the
# latter carries a build hash that changes on deploy, so this one page is both
# the completest source and the most stable.
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

# Postings live at /careers/position/<slugified title>-<id>/. The record carries
# the id and the title but not the slug, so the URL is rebuilt from them; it was
# checked against live postings rather than assumed.
POSTING_URL = "https://www.revolut.com/en-US/careers/position/{slug}-{job_id}/"

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(title: str) -> str:
    return _NON_SLUG.sub("-", title.lower()).strip("-")


def _location(record: dict) -> str | None:
    """Every office the posting lists, marking remote when it says so."""
    names: list[str] = []
    remote = False
    for place in record.get("locations") or []:
        if not isinstance(place, dict):
            continue
        if place.get("type") == "remote":
            remote = True
        name = place.get("name")
        if name and str(name) not in names:
            names.append(str(name))
    place = ", ".join(names)
    if remote and "remote" not in place.lower():
        return f"{place} (Remote)" if place else "Remote"
    return place or None


class RevolutScraper(Scraper):
    """Revolut's careers board, read from the page's embedded data.

    No posted_date: the record carries none, and neither does the posting page.
    """

    config = CompanyConfig(
        name="Revolut",
        career_url=LISTING_URL,
        fetch_mode=FetchMode.RENDERED,
        browser_engine=BROWSER_ENGINE,
        # Not the __NEXT_DATA__ script this scraper actually reads: a script tag
        # is never *visible*, and the render helper waits for visibility. A
        # rendered posting link is the readiness signal, and it only appears
        # once the data this parses has been hydrated.
        wait_for_selector='a[href*="/careers/position/"]',
    )

    def parse(self, payload: str) -> list[Job]:
        match = NEXT_DATA.search(payload)
        if not match:
            return []
        try:
            data = json.loads(match.group(1))
        except ValueError:
            return []
        positions = (data.get("props") or {}).get("pageProps", {}).get("positions")
        if not isinstance(positions, list):
            return []
        jobs: list[Job] = []
        seen: set[str] = set()
        for record in positions:
            if not isinstance(record, dict):
                continue
            job_id = record.get("id")
            title = record.get("text")
            if not (job_id and title) or job_id in seen:
                continue
            seen.add(job_id)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=POSTING_URL.format(slug=_slug(str(title)), job_id=job_id),
                    location=_location(record),
                    posted_date=None,
                )
            )
        return jobs
