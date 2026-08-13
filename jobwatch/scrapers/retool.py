from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Retool runs no third-party ATS: its careers pages are its own, server-rendered,
# and the only complete list of them is the site sitemap. robots.txt allows it.
SITEMAP_URL = "https://retool.com/sitemap.xml"

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Posting URLs are `/careers/<title>--<department>--<location>`, with the three
# parts separated by double hyphens and single hyphens standing in for spaces.
# The listing index itself is `/careers` with no slug and is excluded by
# requiring all three parts.
JOB_PATH = re.compile(r"/careers/(?P<slug>[^/]+)$")

TITLE_SUFFIX = re.compile(r"\s*\|\s*Retool\s*$", re.I)


def _words(part: str) -> str:
    """A slug segment as words. Segments can carry a stray leading or trailing
    hyphen when the title itself ended in one — "…-ai-product-engineer-" then
    "--engineering" reads as "---engineering" — so the edges are trimmed before
    the inner hyphens become spaces."""
    return part.strip("-").replace("-", " ").strip()


class RetoolScraper(Scraper):
    """Retool's own careers pages, listed by the site sitemap.

    The slug carries a lowercased title, which is a placeholder until
    parse_detail reads the page's own `<title>` — that one has the real
    capitalisation and the commas the slug drops ("Software Engineer,
    Observability" against "software engineer observability").

    job_id is the slug, because the pages carry no other identifier. A retitled
    role therefore reads as a new posting, which is the safe direction to be
    wrong in: it over-reports rather than silently missing a job.

    No posted_date: neither the sitemap nor the page publishes one, and the
    sitemap's lastmod is a modification time.
    """

    config = CompanyConfig(
        name="Retool",
        career_url=SITEMAP_URL,
        fetch_mode=FetchMode.STATIC,
    )

    def parse(self, payload: str) -> list[Job]:
        root = ET.fromstring(payload.lstrip("﻿"))
        jobs: list[Job] = []
        seen: set[str] = set()
        for url in root.findall("sm:url", SITEMAP_NS):
            loc = (url.findtext("sm:loc", namespaces=SITEMAP_NS) or "").strip()
            match = JOB_PATH.search(loc)
            if not match:
                continue
            slug = match.group("slug")
            parts = slug.split("--")
            if len(parts) != 3:
                continue
            title = _words(parts[0])
            location = _words(parts[2])
            if not title or slug in seen:
                continue
            seen.add(slug)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=slug,
                    title=title,
                    url=loc,
                    location=location or None,
                    posted_date=None,
                )
            )
        return jobs

    def detail_url(self, job: Job) -> str | None:
        return job.url

    def parse_detail(self, payload: str, job: Job) -> Job:
        match = re.search(r"<title>([^<]*)</title>", payload, re.I)
        if not match:
            return job
        title = TITLE_SUFFIX.sub("", match.group(1)).strip()
        if not title:
            return job
        return Job(
            company=job.company,
            job_id=job.job_id,
            title=title,
            url=job.url,
            location=job.location,
            posted_date=None,
        )
