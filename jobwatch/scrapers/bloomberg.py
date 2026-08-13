from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# careers.bloomberg.com cannot be read at all: it answers 403 to plain HTTP and
# serves an "Are you a robot?" challenge to a real browser. That challenge is
# not something to work around, so that host is simply off the table.
#
# Bloomberg's actual ATS is Avature, on its own host, and that one is open: it
# answers plain HTTP, and its robots.txt explicitly allows `/careers` and
# publishes the sitemap read here. One request covers the whole board — the
# listing pages would be 34 sequential requests, and none of the sort or
# page-size parameters they expose (jobSort, jobSortDirection, sortBy,
# jobRecordsPerPage) is actually honoured, so they could never stop early.
API_URL = "https://bloomberg.avature.net/careers/sitemap.xml"

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Posting URLs are `/careers/JobDetail/<Title-Slug>/<id>`.
JOB_URL = re.compile(r"/careers/JobDetail/(?P<slug>.+)/(?P<job_id>\d+)$")


class BloombergScraper(Scraper):
    """Bloomberg's board, read from its Avature sitemap.

    Titles come from the URL slug, which here is close to lossless: Avature
    builds the slug from the posting title with its capitalisation intact
    ("Senior-iOS-Engineer-Mobile-Professional"), so only punctuation is gone.
    That is a much better trade than on Shopify's sitemap, where the slug is
    lowercased.

    Carries no location, and no posted_date: the sitemap's `lastmod` is a
    modification time, not a publication time, so reporting it as one would
    repeat the mistake the Greenhouse scraper documents about `updated_at`.
    """

    config = CompanyConfig(
        name="Bloomberg",
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
                    title=match.group("slug").replace("-", " ").strip(),
                    url=loc,
                    location=None,
                    posted_date=None,
                )
            )
        return jobs
