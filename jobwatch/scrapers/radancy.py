from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Radancy (formerly TalentBrew) hosts careers portals at jobs.<company>.com —
# and sometimes elsewhere, as Arm's careers.arm.com shows.
#
# Its search pages are the obvious way in and the wrong one: they server-render
# a fixed 15 jobs a page and ignore every widening or reordering parameter tried
# (RecordsPerPage, sortfield, sortby), so a full read is dozens of ~1.8 MB
# requests in an order that cannot be made newest-first — the engine's early
# stop could never apply.
#
# Every Radancy portal publishes its whole board at /rss instead: one request,
# no parameters. Only the feed is read; job detail pages are never fetched.
# (These sites also disallow their search paths in robots.txt, which is not what
# decides this — the request count is.)
RSS_PATH = "/rss"

# company -> portal host. Verified live.
#
# Arm's portal is on careers.arm.com rather than the jobs.<company>.com the
# others use, and nothing on that page says Radancy — only the analytics and CDN
# hosts it loads (radancy.net, tbcdn.talentbrew.com) give it away. Its careers
# site also points at two iCIMS hosts, which are the application step rather
# than the board and answer "Your IP address is not on a trusted network".
BOARDS = {
    "Arm": "https://careers.arm.com",
    "Disney": "https://jobs.disneycareers.com",
    "Intuit": "https://jobs.intuit.com",
}

# Feed titles carry the location in a trailing parenthetical:
# "Staff Software Engineer, Front End - (Mountain View, California, United
# States)". Anchored at the end of the string, because titles ending in a
# qualifier of their own — "Staff Product Manager (Mid-Market)" — must keep it.
TITLE_LOCATION = re.compile(r"^(?P<title>.*?)\s+-\s+\((?P<location>[^()]*)\)\s*$", re.S)


def _job_id(link: str) -> str | None:
    """The posting id is the last path segment of the item link, e.g.
    `/job/mountain-view/staff-software-engineer-front-end/27595/87369440784`.

    Taken from the link rather than the guid: the guid is
    `{id}-{location}-{category}`, and both of those parts contain hyphens and
    commas of their own, so splitting it is guesswork.
    """
    segment = link.rstrip("/").rsplit("/", 1)[-1] if link else ""
    return segment if segment.isdigit() else None


class RadancyScraper(Scraper):
    """One parameterised scraper for every company on a Radancy portal.

    No posted_date. The feed's `pubDate` looks like one and is not: on Intuit's
    board 133 of 388 items share 2026-07-11, while those postings' own JSON-LD
    `datePosted` values are 2025-05-30, 2025-06-16 and 2025-06-17 — over a year
    earlier. It is a feed-regeneration timestamp, the same bulk-re-index pattern
    that makes Greenhouse's `updated_at` unusable. The true date exists only on
    each detail page, which is both a request per posting and, on Disney,
    disallowed by robots.txt. Recency comes from snapshot diffing, as it does
    for Meta.
    """

    def __init__(self, company: str, host: str):
        self.host = host
        self.config = CompanyConfig(
            name=company,
            career_url=f"{host}{RSS_PATH}",
            fetch_mode=FetchMode.STATIC,
        )

    def parse(self, payload: str) -> list[Job]:
        root = ET.fromstring(payload.lstrip("﻿"))
        jobs: list[Job] = []
        for item in root.findall("./channel/item"):
            raw_title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            job_id = _job_id(link)
            if not (raw_title and link and job_id):
                continue
            match = TITLE_LOCATION.match(raw_title)
            title = match.group("title").strip() if match else raw_title
            location = match.group("location").strip() if match else None
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=job_id,
                    title=title,
                    url=link,
                    location=location or None,
                    posted_date=None,
                )
            )
        return jobs


def scrapers() -> list[RadancyScraper]:
    return [RadancyScraper(company, host) for company, host in BOARDS.items()]
