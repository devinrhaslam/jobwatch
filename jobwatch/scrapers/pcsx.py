from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Eightfold's PCSX product, which some customers run on their own apply host
# rather than on the `<tenant>.eightfold.ai` API the plain Eightfold scraper
# uses (Netflix). Both boards here answer
# `403 {"message": "Not authorized for PCSX"}` on the tenant API — a message
# that names the product actually serving the board. PayPal is the second
# company to present exactly that error, and the same reading resolved it.
#
# Neither host needs a key, a CSRF token, or a browser.
API_PATH = "/api/pcsx/search"

# The API returns 10 results per page and ignores every page-size parameter
# tried (num, pageSize, size, limit, rows, pgSz, count, n).
PAGE_SIZE = 10

# company -> (host, domain, max_pages, inter_page_delay_seconds).
#
# Microsoft's board does answer 429 during a seed; the cause turned out to be
# connection churn rather than request rate (the fix was the shared session in
# fetch.py — a seed died at page 33 of 185 even at one second per page). The
# delay is kept only as margin on a board known to rate-limit, and only the seed
# pays for it. PayPal's board is 88 postings, so it needs neither the page
# ceiling nor the pause.
BOARDS = {
    "Microsoft": ("https://apply.careers.microsoft.com", "microsoft.com", 220, 1.0),
    "PayPal": ("https://paypal.eightfold.ai", "paypal.com", 40, 0.0),
    # qualcomm.com/company/careers gives no sign of any of this. The tenant name
    # appears only on the deeper /careers/jobs page, and the plain Eightfold
    # jobs API answers 403 there — PCSX is the one that answers. Its Workday
    # tenant (qualcomm/wd12/External) is live but empty, so it is a decoy.
    # ~1,950 postings at ten a page.
    "Qualcomm": ("https://qualcomm.eightfold.ai", "qualcomm.com", 220, 0.5),
}


def _page_url(host: str, domain: str, start: int) -> str:
    query = urlencode({"domain": domain, "query": "", "location": "", "start": start})
    return f"{host}{API_PATH}?{query}"


def _data(payload: str) -> dict:
    body = json.loads(payload)
    return body.get("data") or {}


def _location(record: dict) -> str | None:
    names = [str(name) for name in (record.get("locations") or []) if name]
    return ", ".join(dict.fromkeys(names)) or None


def _posted_date(record: dict) -> str | None:
    raw = record.get("postedTs")
    if not raw:
        return None
    try:
        return datetime.fromtimestamp(int(raw), timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _posting_url(host: str, record: dict) -> str | None:
    """Prefer the link the API hands out over one built from an id.

    `positionUrl` is site-relative (`/careers/job/<id>`) and resolves directly;
    the jobs.careers.microsoft.com form for the same posting only redirects here.
    """
    path = record.get("positionUrl")
    if path:
        return f"{host}{path}" if str(path).startswith("/") else str(path)
    position_id = record.get("id")
    return f"{host}/careers/job/{position_id}" if position_id else None


class PcsxScraper(Scraper):
    """One parameterised scraper for every board served by Eightfold PCSX.

    Jobs are keyed on `displayJobId` — the requisition number shown on the
    posting — rather than the `id` in the URL, because the requisition survives
    a re-index of the portal's internal ids while still being unique (verified
    across all 1,849 of Microsoft's postings).
    """

    def __init__(
        self,
        company: str,
        host: str,
        domain: str,
        max_pages: int,
        inter_page_delay_seconds: float,
    ):
        self.host = host
        self.domain = domain
        self.config = CompanyConfig(
            name=company,
            career_url=_page_url(host, domain, 0),
            fetch_mode=FetchMode.STATIC,
            max_pages=max_pages,
            inter_page_delay_seconds=inter_page_delay_seconds,
        )

    def parse(self, payload: str) -> list[Job]:
        jobs: list[Job] = []
        for record in _data(payload).get("positions") or []:
            if not isinstance(record, dict):
                continue
            job_id = record.get("displayJobId") or record.get("id")
            title = record.get("name")
            url = _posting_url(self.host, record)
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

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        data = _data(payload)
        if len(data.get("positions") or []) < PAGE_SIZE:
            return None  # a short page means the board is exhausted
        start = int(parse_qs(urlsplit(current_url).query).get("start", ["0"])[0])
        start += PAGE_SIZE
        total = int(data.get("count") or 0)
        if total and start >= total:
            return None
        return _page_url(self.host, self.domain, start)


def scrapers() -> list[PcsxScraper]:
    return [PcsxScraper(company, *settings) for company, settings in BOARDS.items()]
