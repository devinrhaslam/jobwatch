from __future__ import annotations

import re

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

CONFIG = CompanyConfig(
    name="Anthropic",
    career_url="https://www.anthropic.com/jobs",
    fetch_mode=FetchMode.STATIC,
)


class AnthropicScraper(Scraper):
    config = CONFIG

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        jobs: list[Job] = []
        for anchor in soup.select('a[href*="/anthropic/jobs/"]'):
            href = anchor.get("href", "")
            match = re.search(r"/jobs/(\d+)", href)
            captions = anchor.select("p.caption")
            if not match or len(captions) < 2:
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=match.group(1),
                    title=captions[0].get_text(strip=True),
                    url=href,
                    location=captions[1].get_text(strip=True),
                )
            )
        return jobs
