from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Avature portals publish a sitemap that robots.txt names explicitly and that
# carries the whole board in one request. Both boards here are allowed by their
# robots.txt, which names the sitemap read below — the same basis on which the
# Bloomberg scraper reads its Avature host.
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Posting URLs are `/careers/JobDetail/<Title-Slug>/<id>`. The bare
# `/careers/JobDetail` index page is in the sitemap too and is rejected by the
# trailing-id requirement rather than parsed into a titleless job.
JOB_URL = re.compile(r"/careers/JobDetail/(?P<slug>.+)/(?P<job_id>\d+)$")

# company -> sitemap URL. This is the whole URL rather than a tenant name
# because a portal need not live on avature.net at all: EA runs one on its own
# jobs.ea.com, and its sitemap sits under a locale path.
#
# Bloomberg is on this platform too but keeps its own module, whose docstring
# records why careers.bloomberg.com is unreadable and how the Avature host was
# found. Folding it in here would be the tidier arrangement and is worth doing
# as its own change rather than as a side effect of adding these two.
#
# HashiCorp belongs here on paper and is deliberately absent. Its Greenhouse
# board is gone (404), hashicorp.com answers a Vercel bot challenge to plain
# HTTP, and its own careers page sends "Open positions" to
# ibm.com/careers/search?q=hashicorp — IBM acquired it. That search resolves to
# this platform, careers.ibm.com, an Avature portal whose keyword filter is a
# plain GET: /en_US/careers/SearchJobs/?search=<term>&listFilterMode=1. So the
# board is readable; there is simply nothing of HashiCorp's on it. "HashiCorp"
# matches one posting and "Hashi" the same one, and it is an IBM Consulting Red
# Hat architect role that mentions the tool, not a HashiCorp role. IBM does
# brand acquired-company postings — "Senior Software Engineer - Confluent",
# "[Confluent] Senior Integrations Engineer", ten or more of them — so the
# convention exists and HashiCorp has no postings under it today.
#
# Registering it anyway would report a company that fails on every run: the
# engine treats a parse of zero jobs as a failure by design, so it would add a
# permanent failure to each report rather than a quiet empty board. Worth
# re-checking with the search above when IBM starts posting under the brand.
#
# Its Avature sitemap is not the way in either: robots.txt names
# careers.ibm.com/careers/sitemap_index.xml, whose en_US child answers 202 with
# a zero-length body on every attempt, ten in a row over several minutes.
BOARDS = {
    # EA's sitemap index lists eleven locale sitemaps carrying the identical
    # 361 postings under translated paths, so one locale is the whole board and
    # following the index would report every job eleven times.
    "Electronic Arts": "https://jobs.ea.com/en_US/careers/sitemap.xml",
    "Synopsys": "https://synopsys.avature.net/careers/sitemap.xml",
}


def _title(slug: str, job_id: str) -> str:
    """Recover the title from the URL slug.

    Avature builds the slug from the posting title with capitalisation intact,
    so only punctuation is lost. Synopsys additionally repeats the requisition
    id at the end of the slug ("...-Sr-Engineer-12885/12885"), which is not part
    of the title and is stripped when it matches the id in the path.
    """
    if slug.endswith(f"-{job_id}"):
        slug = slug[: -len(job_id) - 1]
    return slug.replace("-", " ").strip()


class AvatureScraper(Scraper):
    """One parameterised scraper for companies on a public Avature portal.

    Carries no location, and no posted_date: a sitemap's `lastmod` is a
    modification time rather than a publication time, so reporting it as one
    would repeat the mistake the Greenhouse scraper documents about
    `updated_at`. Recency comes from snapshot diffing instead.
    """

    def __init__(self, company: str, sitemap_url: str):
        self.config = CompanyConfig(
            name=company,
            career_url=sitemap_url,
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
            title = _title(match.group("slug"), job_id)
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


def scrapers() -> list[AvatureScraper]:
    return [AvatureScraper(company, sitemap) for company, sitemap in BOARDS.items()]
