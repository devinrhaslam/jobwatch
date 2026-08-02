from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

CONFIG = CompanyConfig(
    name="Meta",
    career_url=(
        "https://www.metacareers.com/jobsearch/"
        "?sort_by_new=true&teams[0]=Software%20Engineering&page=1"
    ),
    fetch_mode=FetchMode.RENDERED,
    wait_for_selector='a[href^="/profile/job_details/"]',
)

MAX_META_PAGES = 15
META_PAGE_SIZE = 10


class MetaScraper(Scraper):
    config = CONFIG

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        jobs: list[Job] = []
        for anchor in soup.select('a[href^="/profile/job_details/"]'):
            href = anchor.get("href", "")
            match = re.search(r"/profile/job_details/(\d+)", href)
            title_el = anchor.find("h3")
            if not match or title_el is None:
                continue
            title = title_el.get_text(strip=True)
            texts = list(anchor.stripped_strings)
            location = next((t for t in texts if t != title), None)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=match.group(1),
                    title=title,
                    url=f"https://www.metacareers.com{href}",
                    location=location,
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        parsed = urlparse(current_url)
        query = parse_qs(parsed.query)
        current_page = int(query.get("page", ["1"])[0])
        if len(self.parse(payload)) < META_PAGE_SIZE or current_page >= MAX_META_PAGES:
            return None
        query["page"] = [str(current_page + 1)]
        new_query = urlencode(query, doseq=True, safe="[]")
        return urlunparse(parsed._replace(query=new_query))
