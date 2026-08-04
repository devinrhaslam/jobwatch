from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

SEARCH_URL = "https://careers.twosigma.com/careers/OpenRoles"

PAGE_SIZE = 10
MAX_PAGES = 40

# The portal answers plain HTTP, but only with a browser-shaped Accept header;
# a bare User-Agent gets a response with no listings in it.
REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_JOB_HREF = re.compile(r"/careers/JobDetail/[^/]+/(\d+)")


class TwoSigmaScraper(Scraper):
    """Two Sigma's Avature-hosted career portal, parsed from server-rendered HTML.

    Postings carry no publication date, so recency comes purely from snapshot
    diffing, as with Meta, Snap, and Google. The board is small — around 60
    postings over six pages — so it is read in full each run.
    """

    config = CompanyConfig(
        name="Two Sigma",
        career_url=f"{SEARCH_URL}?{urlencode({'jobOffset': 0})}",
        fetch_mode=FetchMode.STATIC,
        max_pages=MAX_PAGES,
        request_headers=REQUEST_HEADERS,
        # Avature does not order the portal by recency, and with no date on the
        # cards there is no way to confirm it does. Reading every page is cheap
        # at this board size and avoids silently missing a new posting.
        paginate_fully=True,
    )

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        jobs: list[Job] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            match = _JOB_HREF.search(anchor["href"])
            if not match:
                continue
            job_id = match.group(1)
            title = anchor.get_text(" ", strip=True)
            if not title or job_id in seen:
                continue
            seen.add(job_id)
            jobs.append(
                Job(
                    company="Two Sigma",
                    job_id=job_id,
                    title=title,
                    url=anchor["href"],
                    location=_location(anchor),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        soup = BeautifulSoup(payload, "html.parser")
        found = {
            match.group(1)
            for anchor in soup.find_all("a", href=True)
            if (match := _JOB_HREF.search(anchor["href"]))
        }
        if len(found) < PAGE_SIZE:
            return None  # a short page means the board is exhausted
        parsed = urlsplit(current_url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        params["jobOffset"] = str(int(params.get("jobOffset", 0)) + PAGE_SIZE)
        return urlunsplit(parsed._replace(query=urlencode(params)))


def _location(anchor) -> str | None:
    """The first `paragraph_inner-span` in the card is the location; the ones
    after it are the department and career category."""
    card = anchor.find_parent(class_="article__header__text")
    if card is None:
        return None
    span = card.select_one(".article__header__content__text .paragraph_inner-span")
    if span is None:
        return None
    text = span.get_text(" ", strip=True)
    return text or None
