from __future__ import annotations

import re

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# SentinelOne posts to Greenhouse but renders the board itself, server-side, and
# never names the board: nothing on the page or in its network traffic carries
# the slug, and guessing it turned up only 404s. The rendered listing is the
# readable source, and it is a complete one — every posting is in the HTML.
LISTING_URL = "https://www.sentinelone.com/jobs/"

# Each posting links to itself by Greenhouse id. That URL does open the posting
# rather than the listing — its <title> is the job's, over plain HTTP — so
# unlike the boards in EMBED_FALLBACK_BOARDS it needs no substitute.
JOB_HREF = re.compile(r"gh_jid=(\d+)")

# A row renders twice, once for wide screens and once for narrow, so each
# posting appears under two elements and only the link carries the id.
ROW_CLASS = "cursor-pointer"
DESKTOP_GRID = "md:grid"


def _location(anchor) -> str | None:
    """The location column of the row's wide-screen grid.

    That grid is title / location / department in order. The narrow-screen copy
    runs location and department together behind a bullet, so the grid is the
    one worth reading.
    """
    row = anchor.find_parent("div", class_=ROW_CLASS)
    if row is None:
        return None
    grid = row.find("div", class_=lambda value: value and DESKTOP_GRID in value)
    if grid is None:
        return None
    columns = grid.find_all("div", recursive=False)
    if len(columns) < 2:
        return None
    return columns[1].get_text(strip=True) or None


class SentinelOneScraper(Scraper):
    """SentinelOne's own rendering of its Greenhouse board.

    No posted_date: the listing shows none, and the per-posting page is the
    same Greenhouse description without one either.
    """

    config = CompanyConfig(
        name="SentinelOne",
        career_url=LISTING_URL,
        fetch_mode=FetchMode.STATIC,
    )

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        jobs: list[Job] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            match = JOB_HREF.search(anchor["href"])
            if not match:
                continue
            job_id = match.group(1)
            if job_id in seen:
                continue
            title = anchor.get_text(strip=True)
            if not title:
                continue
            seen.add(job_id)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=job_id,
                    title=title,
                    url=f"{LISTING_URL}?gh_jid={job_id}",
                    location=_location(anchor),
                    posted_date=None,
                )
            )
        return jobs
