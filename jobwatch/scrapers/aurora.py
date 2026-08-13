from __future__ import annotations

import json

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# The index aurora.tech/careers renders from. One request covers the board, and
# robots.txt disallows nothing.
API_URL = "https://aurora.tech/api/jobs-index"

# Postings live on Aurora's own site under the job's id.
POSTING_URL = "https://aurora.tech/careers/{job_id}"


def _location(record: dict) -> str | None:
    """Every listed place, plus a remote marker when the board sets one."""
    places = record.get("locations")
    if isinstance(places, str):
        places = [places]
    names = [str(p).strip() for p in (places or []) if p]
    place = ", ".join(dict.fromkeys(names))
    if record.get("isRemote"):
        return f"{place} (Remote)" if place else "Remote"
    return place or None


def _posted_date(record: dict) -> str | None:
    """`publishedDate` is a real publication date.

    It takes only eight distinct values across the board, which looks like a
    fabricated field until you notice they span January to August rather than
    clustering at the moment of the fetch — Aurora posts in batches. The
    `updatedAt` beside it is distinct per posting and is a modification time,
    so it is the one that goes unused.
    """
    raw = record.get("publishedDate")
    if not raw:
        return None
    text = str(raw)[:10]
    return text if len(text) == 10 and text.count("-") == 2 else None


class AuroraScraper(Scraper):
    """Aurora's careers board, read from the index its own page calls.

    The board is Ashby underneath — every `applyLink` carries an `ashby_jid` —
    but Ashby's posting API is opt-in and switched off for this org, so the
    company's own index is the readable source. The reported URL is the
    `/careers/<id>` path the listing links to rather than that applyLink, which
    puts the id in a query parameter.
    """

    config = CompanyConfig(
        name="Aurora",
        career_url=API_URL,
        fetch_mode=FetchMode.STATIC,
    )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("jobs") or []
        jobs: list[Job] = []
        for record in records:
            job_id = record.get("id")
            title = record.get("title")
            if not (job_id and title):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=POSTING_URL.format(job_id=job_id),
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs
