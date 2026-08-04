from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

BASE = "https://www.github.careers"
API_URL = f"{BASE}/api/jobs"
POSTING_URL = f"{BASE}/careers-home/jobs/{{slug}}"

# The API rejects a limit above 100 with a 422. The board is 71 postings today,
# so one request covers it — but it paginates anyway rather than assuming the
# board stays under the cap.
PAGE_SIZE = 100
MAX_PAGES = 40


def _location(record: dict) -> str | None:
    full = record.get("full_location")
    if full:
        return str(full)
    parts = [
        str(record.get(key))
        for key in ("city", "state", "country")
        if record.get(key)
    ]
    return ", ".join(parts) or None


def _posted_date(record: dict) -> str | None:
    raw = record.get("posted_date") or record.get("create_date")
    if not raw:
        return None
    text = str(raw)
    # "2026-08-03T14:02:00+0000" — a UTC offset without the colon that
    # fromisoformat wants on older syntax; normalise it.
    if text.endswith("+0000"):
        text = text[:-5] + "+00:00"
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


class GitHubScraper(Scraper):
    """GitHub's own careers API.

    The board is iCIMS-backed — `apply_url` points at
    careers-githubinc.icims.com — but GitHub fronts it with a JSON API, so this
    reads that rather than scraping iCIMS. Each posting is wrapped in a `data`
    envelope. The apply URL requires a login, so the public careers-home page is
    used as the job link instead.
    """

    config = CompanyConfig(
        name="GitHub",
        career_url=f"{API_URL}?{urlencode({'page': 1, 'limit': PAGE_SIZE})}",
        fetch_mode=FetchMode.STATIC,
        max_pages=MAX_PAGES,
    )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("jobs") or []
        jobs: list[Job] = []
        for wrapper in records:
            record = wrapper.get("data") if isinstance(wrapper, dict) else None
            if not isinstance(record, dict):
                continue
            job_id = record.get("slug") or record.get("req_id")
            title = record.get("title")
            if not (job_id and title):
                continue
            jobs.append(
                Job(
                    company="GitHub",
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=POSTING_URL.format(slug=job_id),
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        data = json.loads(payload)
        records = data.get("jobs") or []
        if len(records) < PAGE_SIZE:
            return None
        parsed = urlsplit(current_url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        page = int(params.get("page", 1)) + 1
        if (page - 1) * PAGE_SIZE >= int(data.get("totalCount") or 0):
            return None
        params["page"] = str(page)
        return urlunsplit(parsed._replace(query=urlencode(params)))
