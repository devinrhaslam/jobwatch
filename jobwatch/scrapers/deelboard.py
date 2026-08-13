from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Deel's job-board product, which hosts boards for its customers and for Deel
# itself. Klarna does not run its own board — klarna.com/careers links out to
# here — and deel.com/careers turns out to be a renderer of the same thing.
#
# Three sources exist for this board, and this scraper uses two:
#
#   - The per-org sitemap, which robots.txt explicitly documents
#     ("Per-org sitemaps are available at /<orgSlug>/sitemap.xml"). It lists
#     every posting and nothing else, but its URLs are bare UUIDs with no title
#     slug — unlike Shopify's or Bloomberg's sitemaps, it carries no data at all
#     beyond the id. Used here for detection.
#   - Each posting's own page, which carries a clean schema.org JobPosting in
#     JSON-LD: title, location and a real datePosted. Used here for enrichment,
#     one fetch per genuinely new posting.
#
# The third source is the React Server Components payload the board streams to
# hydrate itself, which carries everything in a single request. This scraper
# read that until it was rewritten: it works, but it is an internal Next.js
# format with no stability contract, and the pair above are both published
# interfaces. Fewer requests was not worth depending on a private one.
SITEMAP_URL = "https://jobs.deel.com/{org}/sitemap.xml"

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Posting URLs are `/<org>/job-details/<uuid>/overview`.
JOB_URL_TEMPLATE = r"/{org}/job-details/(?P<job_id>[0-9a-f]{{8}}-[0-9a-f-]{{27,}})/overview"

# company -> (org slug, enrichment ceiling). The ceiling is set above the board
# size: a seed reports every posting as new, so it decides how much of the board
# gets a real title, and a posting already seen is never reported again.
BOARDS = {
    "Deel": ("deel", 350),
    "Klarna": ("klarna", 150),
}

# The sitemap has no titles, so a job carries this until its detail page is
# read. It only ever reaches a report if that fetch failed, in which case it is
# the honest thing to show — the link beside it still works.
PENDING_TITLE = "(title unavailable — open the posting)"

JSON_LD = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)


def _job_posting(payload: str) -> dict | None:
    """The posting page carries several JSON-LD blocks — a BreadcrumbList among
    them — so they are searched for the JobPosting rather than assuming it is
    first."""
    for block in JSON_LD.findall(payload):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


def _location(posting: dict) -> str | None:
    names = []
    raw = posting.get("jobLocation")
    entries = raw if isinstance(raw, list) else [raw]
    for entry in entries:
        address = (entry or {}).get("address") if isinstance(entry, dict) else None
        if not isinstance(address, dict):
            continue
        parts = [
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("addressCountry"),
        ]
        name = ", ".join(str(p) for p in parts if p)
        if name and name not in names:
            names.append(name)
    return " | ".join(names) or None


def _posted_date(posting: dict) -> str | None:
    raw = posting.get("datePosted")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


class DeelBoardScraper(Scraper):
    """One parameterised scraper for a board hosted on Deel: sitemap for
    detection, JSON-LD for detail."""

    def __init__(self, company: str, org: str, max_enrichment_fetches: int):
        self.org = org
        self.job_url = re.compile(JOB_URL_TEMPLATE.format(org=re.escape(org)))
        self.config = CompanyConfig(
            name=company,
            career_url=SITEMAP_URL.format(org=org),
            fetch_mode=FetchMode.STATIC,
            max_enrichment_fetches=max_enrichment_fetches,
        )

    def parse(self, payload: str) -> list[Job]:
        root = ET.fromstring(payload.lstrip("\ufeff"))
        jobs: list[Job] = []
        seen: set[str] = set()
        for url in root.findall("sm:url", SITEMAP_NS):
            loc = (url.findtext("sm:loc", namespaces=SITEMAP_NS) or "").strip()
            match = self.job_url.search(loc)
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
                    title=PENDING_TITLE,
                    url=loc,
                    location=None,
                    posted_date=None,
                )
            )
        return jobs

    def detail_url(self, job: Job) -> str | None:
        return job.url

    def parse_detail(self, payload: str, job: Job) -> Job:
        posting = _job_posting(payload)
        if not posting:
            return job
        title = posting.get("title")
        return Job(
            company=job.company,
            job_id=job.job_id,
            title=str(title).strip() if title else job.title,
            url=job.url,
            location=_location(posting),
            posted_date=_posted_date(posting),
        )


def scrapers() -> list[DeelBoardScraper]:
    return [
        DeelBoardScraper(company, org, ceiling)
        for company, (org, ceiling) in BOARDS.items()
    ]
