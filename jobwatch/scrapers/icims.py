from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

SITEMAP_PATH = "/sitemap.xml"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Posting URLs are `/jobs/<id>/<title-slug>/job`. The sitemap also lists
# `/jobs/intro`, which has no id and is rejected here rather than parsed into a
# titleless job.
JOB_URL = re.compile(r"/jobs/(?P<job_id>\d+)/(?P<slug>[^/]+)/job")

# The posting page is a shell that loads its real content in an iframe; the
# same URL with this parameter returns that content directly, including the
# schema.org JobPosting the listing lacks.
IFRAME_PARAM = "in_iframe=1"

# company -> careers host.
#
# An iCIMS host is not always the board. AMD's, Arm's and Booking.com's careers
# pages all link one, and on all three it is the *application* step: the host
# answers 403 "Your IP address is not on a trusted network" to everything,
# including its own sitemap, because it is an internal portal. Their actual
# boards are elsewhere — AMD and Booking.com on their own sites (see jibe.py),
# Arm on Radancy — and all three were briefly written off on the strength of
# that host. Check that a tenant actually serves postings before adding it.
BOARDS = {
    "Joby Aviation": "https://careers-jobyaviation.icims.com",
}


def _title_from_slug(slug: str) -> str:
    """Recover what the listing knows of the title from the URL slug.

    The slug is percent-encoded and lowercased, so this is lossy — "events
    manager" rather than "Events Manager". It is a placeholder until the
    posting's own page supplies the real title in parse_detail, which the engine
    fetches for the jobs it is about to report. The same trade as Klarna's
    sitemap, whose listing carries no title at all.
    """
    return unquote(slug).replace("-", " ").strip()


def _job_posting(payload: str) -> dict | None:
    """The schema.org JobPosting embedded in a posting page, if it parses."""
    for block in re.findall(
        r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', payload, re.S
    ):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("title"):
            return data
    return None


def _location(posting: dict) -> str | None:
    """Every locality the posting lists, in order and deduplicated.

    A role open in several places carries a `jobLocation` entry each, and the
    non-city fields are frequently the literal string "UNAVAILABLE", so only the
    locality is read.
    """
    names: list[str] = []
    for place in posting.get("jobLocation") or []:
        if not isinstance(place, dict):
            continue
        locality = (place.get("address") or {}).get("addressLocality")
        if not locality or str(locality).upper() == "UNAVAILABLE":
            continue
        if str(locality) not in names:
            names.append(str(locality))
    return ", ".join(names) or None


class ICIMSScraper(Scraper):
    """One parameterised scraper for companies on a public iCIMS portal.

    Reads the sitemap robots.txt publishes, which covers the whole board in one
    request, then enriches only the jobs the engine is about to report.

    posted_date is deliberately never set. The JobPosting carries a `datePosted`,
    but it is generated per request: every posting on this board reports exactly
    two years before the moment it was fetched, with the timestamps of a
    sequential crawl incrementing a couple of seconds apart. Reporting that as a
    publication date would be worse than reporting nothing, so recency comes
    from snapshot diffing, as it does for the sitemap-backed boards.
    """

    def __init__(self, company: str, host: str, max_enrichment_fetches: int = 400):
        self.host = host.rstrip("/")
        self.config = CompanyConfig(
            name=company,
            career_url=f"{self.host}{SITEMAP_PATH}",
            fetch_mode=FetchMode.STATIC,
            # Above the size of the board, unlike the engine's default of 120.
            # A seed reports every posting as new, so the cap decides how much
            # of the board gets a real title: at the default, half of Joby's 240
            # kept the lowercased slug, and a job that has already been seen is
            # never reported again, so it would keep that placeholder forever.
            # The cost is one-time — routine runs only enrich genuinely new
            # postings, which is a handful.
            max_enrichment_fetches=max_enrichment_fetches,
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
            title = _title_from_slug(match.group("slug"))
            if not title:
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=job_id,
                    title=title,
                    url=loc,
                    location=None,
                    posted_date=None,
                )
            )
        return jobs

    def detail_url(self, job: Job) -> str | None:
        separator = "&" if "?" in job.url else "?"
        return f"{job.url}{separator}{IFRAME_PARAM}"

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
            posted_date=None,
        )


def scrapers() -> list[ICIMSScraper]:
    return [ICIMSScraper(company, host) for company, host in BOARDS.items()]
