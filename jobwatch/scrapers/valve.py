from __future__ import annotations

import re

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Valve's whole board is on its front page. /en/jobs redirects here, and the
# "Search Jobs" box is a client-side filter over links that are already in the
# HTML — so nothing needs rendering. valvesoftware.com serves no robots.txt.
LISTING_URL = "https://www.valvesoftware.com/en/"

# Postings are `/en/jobs?job_id=<n>`: the id is a query parameter rather than a
# path segment, which is why a scan for path-shaped job URLs finds nothing here.
# Unlike the boards in the Greenhouse EMBED_FALLBACK set, this one does open the
# posting — `?job_id=85` answers with "Audio Software Engineer Careers" as its
# title over plain HTTP.
JOB_ID = re.compile(r"job_id=(\d+)")

POSTING_URL = "https://www.valvesoftware.com/en/jobs?job_id={job_id}"


class ValveScraper(Scraper):
    """Valve's careers listing.

    Each posting is linked from more than one section of the page, so ids are
    deduplicated; the first link for an id carries the title.

    No location or posted_date: the page shows neither, and Valve describes
    itself as hiring for broad areas rather than dated openings.
    """

    config = CompanyConfig(
        name="Valve",
        career_url=LISTING_URL,
        fetch_mode=FetchMode.STATIC,
    )

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        jobs: list[Job] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            match = JOB_ID.search(anchor["href"])
            if not match:
                continue
            job_id = match.group(1)
            # A separator matters here: several titles are split across nested
            # elements ("Software Engineering" + "Other"), and joining them with
            # nothing produces "Software EngineeringOther".
            title = " ".join(anchor.stripped_strings)
            if not title or job_id in seen:
                continue
            seen.add(job_id)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=job_id,
                    title=title,
                    url=POSTING_URL.format(job_id=job_id),
                    location=None,
                    posted_date=None,
                )
            )
        return jobs
