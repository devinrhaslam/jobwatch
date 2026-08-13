from __future__ import annotations

import re

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Zed runs no ATS. Its jobs page is server-rendered and lists every opening as a
# link to a page on the same site; robots.txt allows everything but Next.js
# build artefacts.
LISTING_URL = "https://zed.dev/jobs"

# Postings are `/jobs/<slug>`; the page's own anchors and section links share
# the prefix, so a slug with a further path segment or a fragment is not one.
JOB_PATH = re.compile(r"^/jobs/(?P<slug>[a-z0-9][a-z0-9-]*)$")


class ZedScraper(Scraper):
    """Zed's own jobs page.

    A small board — two openings at the time of writing — so the listing is the
    whole of it, and the anchor text is the title.

    No location or posted_date: the listing shows neither, and each posting's
    page gives a prose description rather than a labelled field.
    """

    config = CompanyConfig(
        name="Zed",
        career_url=LISTING_URL,
        fetch_mode=FetchMode.STATIC,
    )

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        jobs: list[Job] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            match = JOB_PATH.match(anchor["href"].strip())
            if not match:
                continue
            slug = match.group("slug")
            title = anchor.get_text(strip=True)
            if not title or slug in seen:
                continue
            seen.add(slug)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=slug,
                    title=title,
                    url=f"{LISTING_URL}/{slug}",
                    location=None,
                    posted_date=None,
                )
            )
        return jobs
