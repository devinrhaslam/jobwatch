from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

CONFIG = CompanyConfig(
    name="Cloudflare",
    career_url="https://www.cloudflare.com/careers/#open-roles",
    fetch_mode=FetchMode.RENDERED,
    wait_for_selector='a[href*="boards.greenhouse.io/cloudflare/jobs/"]',
)


def _parse_posted_date(text: str) -> str | None:
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


class CloudflareScraper(Scraper):
    config = CONFIG

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        by_id: dict[str, Job] = {}
        for anchor in soup.select('a[href*="boards.greenhouse.io/cloudflare/jobs/"]'):
            href = anchor.get("href", "")
            match = re.search(r"/jobs/(\d+)", href)
            paragraphs = [p.get_text(strip=True) for p in anchor.find_all("p")]
            if not match or len(paragraphs) < 2:
                continue
            job_id = match.group(1)
            if job_id in by_id:
                continue
            posted_date = None
            if len(paragraphs) >= 3:
                posted_match = re.match(r"^Posted\s+(.+)$", paragraphs[2])
                if posted_match:
                    posted_date = _parse_posted_date(posted_match.group(1))
            by_id[job_id] = Job(
                company=self.config.name,
                job_id=job_id,
                title=paragraphs[0],
                url=href,
                location=paragraphs[1],
                posted_date=posted_date,
            )
        return list(by_id.values())
