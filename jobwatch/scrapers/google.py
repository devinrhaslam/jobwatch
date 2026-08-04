from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

BASE = "https://www.google.com/about/careers/applications"
SEARCH_URL = f"{BASE}/jobs/results/"

PAGE_SIZE = 20
MAX_PAGES = 60

# Google's board spans every function and runs to thousands of postings, so the
# entry URL narrows at source with its own query — the approach Meta's and
# Amazon's scrapers already take. sort_by=date is what keeps the engine's early
# stop safe, since the cards carry no date of their own.
QUERY = {"q": "software engineer", "sort_by": "date", "page": 1}

_JOB_HREF = re.compile(r"jobs/results/(\d+)")


class GoogleScraper(Scraper):
    """Google's careers search results, parsed from server-rendered HTML.

    There is no public JSON API — the page is rendered by Google's BOQ
    framework, whose class names are build-generated and change without notice.
    So this keys off the job href pattern and structural position (the card is
    an `li[ssk]`, its title the card's `h3`, its location the span carrying the
    `place` material icon), never off a class name.

    The cards expose no posting date, so recency comes from snapshot diffing,
    as with Meta and Snap.
    """

    config = CompanyConfig(
        name="Google",
        career_url=f"{SEARCH_URL}?{urlencode(QUERY)}",
        fetch_mode=FetchMode.STATIC,
        max_pages=MAX_PAGES,
    )

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        jobs: list[Job] = []
        seen: set[str] = set()
        for card in soup.select("li[ssk]"):
            anchor = next(
                (
                    a
                    for a in card.find_all("a", href=True)
                    if _JOB_HREF.search(a["href"])
                ),
                None,
            )
            heading = card.find("h3")
            if anchor is None or heading is None:
                continue
            match = _JOB_HREF.search(anchor["href"])
            if not match:
                continue
            job_id = match.group(1)
            if job_id in seen:
                continue
            seen.add(job_id)
            href = anchor["href"]
            jobs.append(
                Job(
                    company="Google",
                    job_id=job_id,
                    title=heading.get_text(strip=True),
                    url=href if href.startswith("http") else f"{BASE}/{href.lstrip('/')}",
                    location=_location(card),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        soup = BeautifulSoup(payload, "html.parser")
        if len(soup.select("li[ssk]")) < PAGE_SIZE:
            return None  # a short page means the results are exhausted
        parsed = urlsplit(current_url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        params["page"] = str(int(params.get("page", 1)) + 1)
        return urlunsplit(parsed._replace(query=urlencode(params)))


def _location(card) -> str | None:
    """The location sits in the span that also holds the `place` material icon.
    Reading the icon rather than a class name keeps this stable across builds.
    """
    for icon in card.select("i"):
        if icon.get_text(strip=True) != "place":
            continue
        container = icon.parent
        if container is None:
            continue
        text = container.get_text(" ", strip=True)
        cleaned = text.replace("place", "", 1).strip()
        # Long multi-site lists end in a "+ N more locations" affordance.
        cleaned = re.sub(r"\s*\+\s*\d+\s+more locations?.*$", "", cleaned, flags=re.I)
        if cleaned:
            return cleaned
    return None
