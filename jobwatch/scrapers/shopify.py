from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Shopify runs its own careers app, and its search page cannot be read over
# plain HTTP: it rate-limits non-browser requests, answering 429 on
# `/careers/search.json` and, once throttled, serving the search page with zero
# job links rather than an error. Consecutive plain fetches returned 31 links
# and then 0. Nothing in the page is a usable board.
#
# The careers sitemap is the stable source: one request, the whole board, and
# unchanged across repeated calls. Every entry is a posting — 109 of 109, no
# marketing pages mixed in.
API_URL = "https://www.shopify.com/careers/sitemap.xml"

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Posting URLs are `/careers/<slug>_<uuid>`; the uuid is the job id.
JOB_URL = re.compile(r"/careers/(?P<slug>[a-z0-9-]+)_(?P<job_id>[0-9a-f]{8}-[0-9a-f-]+)$")

# Slug words that a plain title-casing gets wrong.
ACRONYMS = {
    "ai", "api", "aws", "bi", "cx", "eu", "hr", "it", "ml", "pr", "qa", "sec",
    "seo", "smb", "sre", "uk", "us", "ux", "ui",
}


def _title_from_slug(slug: str) -> str:
    """The sitemap carries no title, so it is recovered from the URL slug.

    Lossy by nature — the slug has already lost case and punctuation, so
    "senior-lead-uk-public-affairs" can only come back as "Senior Lead UK
    Public Affairs", never with its original comma or parenthetical. Good
    enough to recognise a posting in a report, which is what it is for.
    """
    words = [w for w in slug.split("-") if w]
    return " ".join(w.upper() if w in ACRONYMS else w.capitalize() for w in words)


class ShopifyScraper(Scraper):
    """Reads Shopify's board from its careers sitemap.

    Carries no location and no posted_date, because the sitemap has neither.
    Its `lastmod` values are all distinct and span months, so they are real
    per-posting timestamps rather than a regeneration stamp — but `lastmod` is
    a modification time, not a publication time, so reporting it as one would
    repeat the mistake the Greenhouse scraper documents about `updated_at`.
    Recency comes from snapshot diffing, as it does for Meta.
    """

    config = CompanyConfig(
        name="Shopify",
        career_url=API_URL,
        fetch_mode=FetchMode.STATIC,
    )

    def parse(self, payload: str) -> list[Job]:
        root = ET.fromstring(payload.lstrip("﻿"))
        jobs: list[Job] = []
        seen: set[str] = set()
        for url in root.findall("sm:url", SITEMAP_NS):
            loc = (url.findtext("sm:loc", namespaces=SITEMAP_NS) or "").strip()
            match = JOB_URL.search(loc)
            if not match:
                continue
            job_id = match.group("job_id")
            if job_id in seen:
                continue
            seen.add(job_id)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=job_id,
                    title=_title_from_slug(match.group("slug")),
                    url=loc,
                    location=None,
                    posted_date=None,
                )
            )
        return jobs
