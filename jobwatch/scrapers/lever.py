from __future__ import annotations

import json
from datetime import datetime, timezone

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# `mode=json` is what makes this endpoint return the postings as data rather
# than the rendered board page. The whole board comes back in one response.
API_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"

# Companies whose public job board is hosted by Lever, keyed by company name ->
# board slug. Verified live by tools/probe_ats.py.
BOARDS = {
    # Tinder, Hinge and the rest post to one Match Group board, so the postings
    # name the brand rather than the parent.
    "Match Group": "matchgroup",
    "Palantir": "palantir",
    # Shield AI also has a live Ashby board with almost the same postings (430
    # vs 434). Lever is the one shield.ai/careers actually links to, so its
    # links are the ones a candidate would follow.
    "Shield AI": "shieldai",
    "Spotify": "spotify",
    # careers.veeva.com is a WordPress site that renders this board itself; the
    # only trace of Lever is its JavaScript building links out of a `lever_id`.
    # The slug is the bare brand, so guessing from the listed name
    # ("Veeva Systems" -> veevasystems) never reaches it.
    "Veeva Systems": "veeva",
    "Zoox": "zoox",
}


def _location(record: dict) -> str | None:
    """Primary location plus any extra ones, matching how the Greenhouse and
    Ashby scrapers present multi-site roles.

    `categories.location` names a single site even when the role is open in
    several: 32 of Spotify's 102 postings list more in `allLocations`, so
    reading only the primary would hide half the places a job can be taken.
    """
    categories = record.get("categories") or {}
    names: list[str] = []
    primary = categories.get("location")
    if primary:
        names.append(str(primary))
    for extra in categories.get("allLocations") or []:
        if extra and str(extra) not in names:
            names.append(str(extra))
    return ", ".join(names) or None


def _posted_date(record: dict) -> str | None:
    """`createdAt` is epoch milliseconds, and is the posting's creation time
    rather than a re-index timestamp — the same property that makes Greenhouse's
    `first_published` trustworthy and its `updated_at` not."""
    raw = record.get("createdAt")
    if not isinstance(raw, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(raw / 1000, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


class LeverScraper(Scraper):
    """One parameterised scraper for every company on a public Lever board.

    Same reasoning as the Greenhouse and Ashby scrapers: Lever is the ATS
    recruiters post into, so its postings API is the upstream source rather than
    a mirror, and it carries a real creation timestamp.
    """

    def __init__(self, company: str, slug: str):
        self.slug = slug
        self.config = CompanyConfig(
            name=company,
            career_url=API_URL.format(slug=slug),
            fetch_mode=FetchMode.STATIC,
        )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload)
        if not isinstance(records, list):
            return []
        jobs: list[Job] = []
        for record in records:
            job_id = record.get("id")
            title = record.get("text")
            # hostedUrl is the posting page; applyUrl is the same page's apply
            # form. Prefer the posting so a report link opens the description.
            url = record.get("hostedUrl") or record.get("applyUrl")
            if not (job_id and title and url):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=url,
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs


def scrapers() -> list[LeverScraper]:
    return [LeverScraper(company, slug) for company, slug in BOARDS.items()]
