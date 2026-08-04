from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

BASE = "https://jobs.apple.com"
SEARCH_URL = f"{BASE}/en-us/search"

PAGE_SIZE = 20
MAX_PAGES = 40

# Narrowing at source is mandatory here, not an optimisation. Unfiltered, the
# board exposes only ~81 postings and every one is team=APPST (Apple Retail) —
# no engineering role is reachable at all, whatever the sort.
#
# The filter that works is `team=<TEAM>-<SUBTEAM>`, using Apple's own codes.
# This is easy to get wrong: `search`, `keyword`, and `query` do nothing and
# additionally break pagination, and a team value built from the label slug
# ("cloud-and-infrastructure-CLD") is silently ignored. Only the code pair
# filters. Subteam codes come from the "View all teams" panel.
SOFTWARE_SUBTEAMS = (
    "AF",      # Apps and Frameworks
    "CLD",     # Cloud and Infrastructure
    "COS",     # Core Operating Systems
    "DSR",     # DevOps and Site Reliability
    "ISTECH",  # Information Systems and Technology
    "MCHLN",   # Machine Learning and AI
    "SEC",     # Security and Privacy
    "SQAT",    # Software Quality, Automation, and Tools
    "WSFT",    # Wireless Software
)
QUERY = {
    "sort": "newest",
    "team": [f"SFTWR-{code}" for code in SOFTWARE_SUBTEAMS],
    "page": 1,
}

# Ids carry a suffix on filtered pages ("200674969-0351") but not on unfiltered
# ones ("200313970"), so both shapes have to match.
_JOB_HREF = re.compile(r"/details/(\d[\d-]*)/")


def _location(card) -> str | None:
    """The location column renders differently between the unfiltered board and
    a team-filtered one: filtered cards carry a bare span, unfiltered ones a
    `table--advanced-search__location-sub`. Read the column and drop its
    screen-reader "Location" label rather than depending on either shape.
    """
    column = card.select_one(".job-title-location")
    if column is None:
        return None
    for hidden in column.select(".a11y"):
        hidden.decompose()
    text = column.get_text(" ", strip=True)
    return text or None


def _posted_date(text: str) -> str | None:
    """Cards render "Aug 04, 2026"."""
    cleaned = " ".join((text or "").split())
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


class AppleScraper(Scraper):
    """Apple's careers search, parsed from server-rendered HTML.

    Apple exposes no public jobs API, so this parses server-rendered HTML and
    narrows at source through Apple's own team filter — see SOFTWARE_SUBTEAMS
    for why that particular parameter shape is the only one that works.

    Unlike Google's careers site, the markup here carries semantic class names
    (`job-list-item`, `team-name`, `job-posted-date`) rather than build-hashed
    ones, so those are matched directly. The job id still comes from the href
    pattern, which is the most stable signal on the page.
    """

    config = CompanyConfig(
        name="Apple",
        career_url=f"{SEARCH_URL}?{urlencode(QUERY, doseq=True)}",
        fetch_mode=FetchMode.STATIC,
        max_pages=MAX_PAGES,
    )

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        jobs: list[Job] = []
        seen: set[str] = set()
        for card in soup.select(".job-list-item"):
            anchor = next(
                (a for a in card.find_all("a", href=True) if _JOB_HREF.search(a["href"])),
                None,
            )
            if anchor is None:
                continue
            job_id = _JOB_HREF.search(anchor["href"]).group(1)
            title = anchor.get_text(" ", strip=True)
            if not title or job_id in seen:
                continue
            seen.add(job_id)
            href = anchor["href"]
            date_el = card.select_one(".job-posted-date")
            location = _location(card)
            jobs.append(
                Job(
                    company="Apple",
                    job_id=job_id,
                    title=title,
                    url=href if href.startswith("http") else f"{BASE}{href}",
                    location=location,
                    posted_date=_posted_date(date_el.get_text(strip=True)) if date_el else None,
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        soup = BeautifulSoup(payload, "html.parser")
        if len(soup.select(".job-list-item")) < PAGE_SIZE:
            return None  # a short page means the board is exhausted
        parsed = urlsplit(current_url)
        # parse_qs keeps every value, which matters: the team filter is a
        # repeated parameter and collapsing it to one would silently widen the
        # search back to the retail-only board.
        params = parse_qs(parsed.query)
        params["page"] = [str(int(params.get("page", ["1"])[0]) + 1)]
        return urlunsplit(parsed._replace(query=urlencode(params, doseq=True)))
