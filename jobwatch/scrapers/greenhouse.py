from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
CANONICAL_POSTING_URL = "https://job-boards.greenhouse.io/{slug}/jobs/{job_id}"

# Companies whose careers page is a downstream renderer of a public Greenhouse
# board, keyed by company name -> board slug. Verified live by tools/probe_ats.py.
#
# LinkedIn is deliberately absent: it matches three different boards (Greenhouse
# 53 jobs, Lever 23) and none is plausibly LinkedIn's real volume, so it needs
# individual recon rather than an assumed slug.
BOARDS = {
    "Airbnb": "airbnb",
    "Anthropic": "anthropic",
    "Block": "block",
    "Cloudflare": "cloudflare",
    "Coinbase": "coinbase",
    "Databricks": "databricks",
    "Dropbox": "dropbox",
    "Figma": "figma",
    "Jane Street": "janestreet",
    "Lyft": "lyft",
    "MongoDB": "mongodb",
    "Pinterest": "pinterest",
    "Reddit": "reddit",
    "SpaceX": "spacex",
    "Stripe": "stripe",
    "Twitch": "twitch",
    "Vercel": "vercel",
    "Waymo": "waymo",
}


def _location(record: dict) -> str | None:
    """Prefer a metadata location over the top-level one.

    Some boards use `location.name` for the work arrangement rather than a place
    — Cloudflare's reads "Hybrid" / "In-Office" / "Distributed" — and put the
    actual city in a metadata field. Boards without such a field (Stripe,
    Airbnb) fall through to `location.name`, and a metadata entry with no value
    (Anthropic's "Location Type") is skipped rather than blanking the location.
    """
    for entry in record.get("metadata") or []:
        if "location" not in (entry.get("name") or "").lower():
            continue
        value = entry.get("value")
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if item)
        if value:
            return str(value)
    name = (record.get("location") or {}).get("name")
    return name or None


def _posting_url(record: dict, slug: str, job_id: str) -> str:
    """Prefer the company's own posting URL, but only when it actually
    identifies the job in its path.

    Some boards point `absolute_url` at a generic listing page with the job id
    only in a query parameter — Stripe's is `stripe.com/jobs/search?gh_jid=N`
    and Pinterest's `pinterestcareers.com/jobs/?gh_jid=N`. Those depend on the
    company's own JavaScript to deep-link, and when the posting has closed they
    silently render the full search listing instead, which reads as "the link
    took me to the jobs page, not the job". The canonical Greenhouse URL
    redirects to the same destination while the posting is open, and to an
    explicit error page once it is not.
    """
    absolute = record.get("absolute_url") or ""
    path = urlsplit(absolute).path if absolute else ""
    if absolute and re.search(rf"/{re.escape(job_id)}(?:/|$)", path):
        return absolute
    return CANONICAL_POSTING_URL.format(slug=slug, job_id=job_id)


def _posted_date(record: dict) -> str | None:
    """Only `first_published` is a real posting time. `updated_at` moves in bulk
    re-indexes — every Anthropic job shared one timestamp — so it would report a
    stale listing as posted today."""
    raw = record.get("first_published")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        return None


class GreenhouseScraper(Scraper):
    """One parameterised scraper for every company on a public Greenhouse board.

    Greenhouse is the ATS recruiters post into; a company's careers page renders
    from it. Reading the board API directly is therefore the upstream source,
    not a third-party mirror, and it carries a real publication timestamp that
    most careers pages omit.
    """

    def __init__(self, company: str, slug: str):
        self.slug = slug
        self.config = CompanyConfig(
            name=company,
            career_url=API_URL.format(slug=slug),
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
            job_id = str(job_id)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=job_id,
                    title=title.strip(),
                    url=_posting_url(record, self.slug, job_id),
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs


def scrapers() -> list[GreenhouseScraper]:
    return [GreenhouseScraper(company, slug) for company, slug in BOARDS.items()]
