from __future__ import annotations

import json
from datetime import datetime

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"

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
            url = record.get("absolute_url")
            if not (job_id and title and url):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=title.strip(),
                    url=url,
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs


def scrapers() -> list[GreenhouseScraper]:
    return [GreenhouseScraper(company, slug) for company, slug in BOARDS.items()]
