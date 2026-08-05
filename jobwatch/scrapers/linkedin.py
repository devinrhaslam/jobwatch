from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlsplit

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# LinkedIn hosts its own openings on its own job platform rather than a
# third-party ATS. This reads the guest endpoint LinkedIn serves to logged-out
# visitors: no account, no session cookie, and no bot-detection to get around.
API_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
POSTING_URL = "https://www.linkedin.com/jobs/view/{job_id}"

# LinkedIn's careers page searches these company ids — the main company plus the
# sub-entities it posts under.
COMPANY_IDS = "1337,9202023,2561065,2587638,290903,39939"

# A rolling recency window rather than the whole board, which is the one thing
# that makes this company workable. Two facts force it:
#
#   1. The results are not ordered by date. `sortBy=DD` is accepted and then
#      ignored — it returns exactly the relevance ordering, dates interleaved —
#      so the engine's early stop, which assumes newest-first, is unsafe here.
#   2. The endpoint rate-limits hard, answering 429 after about four pages.
#
# Together those would mean reading a whole unordered board on every run
# against a limiter that refuses it. `f_TPR` sidesteps both: it asks for only
# recently-posted jobs, which is what this tool wants anyway. A week is used
# rather than a day so that a missed run does not lose postings.
#
# The cost is that this company's snapshot is a rolling window, not a record of
# the whole board: a gap of more than a week leaves jobs unseen. See the README.
TIME_POSTED_WINDOW = "r604800"  # seconds; 7 days

PAGE_SIZE = 10
MAX_PAGES = 20  # the window runs to ~5 pages; this is headroom, not a target

# Well above the engine default. The limiter here is strict and this company is
# cheap anyway — the window is a handful of pages.
INTER_PAGE_DELAY_SECONDS = 4.0

_JOB_URN = re.compile(r"urn:li:jobPosting:(\d+)")


def _page_url(start: int) -> str:
    query = urlencode(
        {"f_C": COMPANY_IDS, "f_TPR": TIME_POSTED_WINDOW, "start": start}
    )
    return f"{API_URL}?{query}"


def _text(card, selector: str) -> str | None:
    element = card.select_one(selector)
    if element is None:
        return None
    return element.get_text(strip=True) or None


class LinkedInScraper(Scraper):
    """LinkedIn's own openings, read from its logged-out guest jobs endpoint.

    Job links are rebuilt from the posting id rather than taken from the card's
    href, which carries per-request tracking parameters (`refId`, `trackingId`,
    `position`) that would make the same posting look like a different URL on
    every run — and `Job.stable_id` hashes the URL.
    """

    config = CompanyConfig(
        name="LinkedIn",
        career_url=_page_url(0),
        fetch_mode=FetchMode.STATIC,
        max_pages=MAX_PAGES,
        inter_page_delay_seconds=INTER_PAGE_DELAY_SECONDS,
        # The window is not date-ordered, so a page of already-known jobs says
        # nothing about the pages after it.
        paginate_fully=True,
    )

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        jobs: list[Job] = []
        for card in soup.select("li"):
            holder = card.select_one("[data-entity-urn]")
            match = _JOB_URN.search(holder.get("data-entity-urn", "")) if holder else None
            title = _text(card, "h3")
            if not (match and title):
                continue
            job_id = match.group(1)
            posted = card.select_one("time")
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=job_id,
                    title=title,
                    url=POSTING_URL.format(job_id=job_id),
                    location=_text(card, ".job-search-card__location"),
                    posted_date=(posted.get("datetime") if posted else None) or None,
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        jobs = self.parse(payload)
        if len(jobs) < PAGE_SIZE:
            return None  # a short page means the window is exhausted
        start = int(parse_qs(urlsplit(current_url).query).get("start", ["0"])[0])
        return _page_url(start + PAGE_SIZE)
