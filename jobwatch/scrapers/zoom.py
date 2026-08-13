from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# careers.zoom.us answers 202 with an empty body to a plain request for any job
# page, but its sitemap is served normally and robots.txt publishes it by name
# while disallowing only /api/, /me/ and a couple of other paths. So the board
# is readable without a browser even though an individual posting is not.
SITEMAP_URL = "https://careers.zoom.us/sitemap.xml"

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

JOB_URL = re.compile(r"/jobs/(?P<slug>[^/]+)/?$")

# Some slugs end in the posting's uuid and some do not; where it is present it
# is not part of the title.
TRAILING_UUID = re.compile(
    r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _title(slug: str) -> str:
    """Recover what the sitemap knows of the title.

    This is lossy in a way worth being explicit about: the slug runs the title
    and the location together with no separator — "staff-ai-engineer-seattle-
    washington-united-states" — and lowercases both, so the reported title reads
    "staff ai engineer seattle washington united states". The posting's own page
    separates them ("Staff AI Engineer - Seattle, Washington, United States")
    but answers 202 to anything that is not a browser, so there is nothing to
    enrich from over plain HTTP. A whole title plus its location beats missing
    the posting.
    """
    return TRAILING_UUID.sub("", slug).replace("-", " ").strip()


class ZoomScraper(Scraper):
    """Zoom's careers board, read from the sitemap because the postings are not
    readable directly.

    No location or posted_date: the sitemap carries neither, and its `lastmod`
    is a modification time.
    """

    config = CompanyConfig(
        name="Zoom",
        career_url=SITEMAP_URL,
        fetch_mode=FetchMode.STATIC,
        # robots.txt asks for five seconds between requests. Only one is made,
        # but the setting records the site's stated limit.
        inter_page_delay_seconds=5.0,
    )

    def parse(self, payload: str) -> list[Job]:
        root = ET.fromstring(payload.lstrip("﻿"))
        jobs: list[Job] = []
        seen: set[str] = set()
        for url in root.findall("sm:url", SITEMAP_NS):
            loc = (url.findtext("sm:loc", namespaces=SITEMAP_NS) or "").strip()
            match = JOB_URL.search(loc)
            if not match:
                continue
            slug = match.group("slug")
            title = _title(slug)
            if not title or slug in seen:
                continue
            seen.add(slug)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=slug,
                    title=title,
                    url=loc,
                    location=None,
                    posted_date=None,
                )
            )
        return jobs
