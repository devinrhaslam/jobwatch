from __future__ import annotations

import json
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# iCIMS's career-site product (formerly Jibe): a company-branded site on the
# company's own domain that answers its board from `/api/jobs`, alongside the
# `/api/jasession` and `/api/trackcdn` calls that identify it. Both boards here
# front an iCIMS ATS for the application step — careers-amd.icims.com and
# external-workingatbooking.icims.com — but neither of those hosts serves the
# board, and both answer 403 "Your IP address is not on a trusted network".
# The public site is the readable one and allows everything in robots.txt.
API_PATH = "/api/jobs?page=1&limit={limit}&internal=false&sortBy=posted_date&descending=true"

# `limit` is honoured; the other page-size spellings the API accepts (size,
# per_page, pageSize) are silently ignored and leave the default of ten.
PAGE_SIZE = 100

# company -> (api host, posting URL template, extra query parameters).
#
# Booking.com needs the tag filter its own careers site applies: without it the
# board answers 156 postings spanning sibling Booking Holdings brands rather
# than the 106 that are Booking.com's own.
BOARDS = {
    "AMD": (
        "https://careers.amd.com",
        "https://careers.amd.com/careers-home/jobs/{slug}",
        {},
    ),
    "Booking.com": (
        "https://jobs.booking.com",
        "https://jobs.booking.com/booking/jobs/{slug}",
        {"tags1": "Booking.com Company Hierarchy|Transport Company Hierarchy"},
    ),
}


def _location(record: dict) -> str | None:
    """City, state and country. `location_name` is an internal site code
    ("CA,ON,Markham-1CV") rather than a place."""
    parts = [
        str(record[key]).strip()
        for key in ("city", "state", "country")
        if record.get(key)
    ]
    return ", ".join(dict.fromkeys(parts)) or None


def _posted_date(record: dict) -> str | None:
    """`posted_date` is real: the board is ordered by it, and it runs from today
    on page one back to a year ago on the last page. `update_date` beside it is
    a modification time."""
    raw = record.get("posted_date")
    if not raw:
        return None
    text = str(raw)[:10]
    return text if len(text) == 10 and text.count("-") == 2 else None


class JibeScraper(Scraper):
    """One parameterised scraper for companies on an iCIMS career site.

    The board comes back newest-first, so the engine's early stop applies and a
    routine run reads one page rather than the whole board.
    """

    def __init__(self, company: str, host: str, posting_url: str, extra: dict):
        self.posting_url = posting_url
        url = f"{host}{API_PATH.format(limit=PAGE_SIZE)}"
        if extra:
            parsed = urlsplit(url)
            params = parse_qs(parsed.query)
            params.update({k: [v] for k, v in extra.items()})
            url = urlunsplit(parsed._replace(query=urlencode(params, doseq=True)))
        self.config = CompanyConfig(
            name=company,
            career_url=url,
            fetch_mode=FetchMode.STATIC,
            # robots.txt on both hosts asks for five seconds between requests.
            inter_page_delay_seconds=5.0,
            max_pages=30,
        )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("jobs") or []
        jobs: list[Job] = []
        for entry in records:
            record = entry.get("data") if isinstance(entry, dict) else None
            if not isinstance(record, dict):
                continue
            slug = record.get("slug") or record.get("req_id")
            title = record.get("title")
            if not (slug and title):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(slug),
                    title=str(title).strip(),
                    url=self.posting_url.format(slug=slug),
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        records = json.loads(payload).get("jobs") or []
        if len(records) < PAGE_SIZE:
            return None  # a short page means the board is exhausted
        parsed = urlsplit(current_url)
        params = parse_qs(parsed.query)
        params["page"] = [str(int(params.get("page", ["1"])[0]) + 1)]
        return urlunsplit(parsed._replace(query=urlencode(params, doseq=True)))


def scrapers() -> list[JibeScraper]:
    return [
        JibeScraper(company, host, posting_url, extra)
        for company, (host, posting_url, extra) in BOARDS.items()
    ]
