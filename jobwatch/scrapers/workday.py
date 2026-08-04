from __future__ import annotations

import json
import re
from datetime import date, timedelta
from urllib.parse import urlsplit

from jobwatch.fetch import build_post_url, split_post_url
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Workday's public "CXS" search endpoint. tenant/site vary per company and the
# wd<N> number identifies which Workday cluster hosts the tenant.
API_URL = "https://{tenant}.{cluster}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"

# The board rejects a page size above 20, so seeding a large tenant takes many
# requests. Routine runs stay cheap because results are newest-first and the
# engine stops paginating at the first page contributing no unseen ids.
PAGE_SIZE = 20

# Enough pages to seed the largest tenant here (NVIDIA, ~2000 postings).
MAX_PAGES = 120

# company -> (tenant, cluster, site). Verified live against the CXS endpoint.
BOARDS = {
    "CrowdStrike": ("crowdstrike", "wd5", "crowdstrikecareers"),
    "NVIDIA": ("nvidia", "wd5", "NVIDIAExternalCareerSite"),
    "Salesforce": ("salesforce", "wd12", "External_Career_Site"),
}

_RELATIVE_DAYS = re.compile(r"posted\s+(\d+)\+?\s+days?\s+ago", re.I)
_POSTED_TODAY = re.compile(r"posted\s+today", re.I)
_POSTED_YESTERDAY = re.compile(r"posted\s+yesterday", re.I)

# "3 Locations" — a count, not a place.
_LOCATION_COUNT = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)
# externalPath looks like /job/India---Hyderabad/Software-Engineer_JR1
_PATH_LOCATION = re.compile(r"^/job/([^/]+)/")


def _location(record: dict) -> str | None:
    """Workday reports a bare count for any multi-site role, which is useless
    for deciding whether a job is somewhere you would take it. The posting path
    still names the primary site, so fall back to that: roughly a third of the
    postings on these boards would otherwise carry no usable location at all.
    """
    text = (record.get("locationsText") or "").strip()
    if text and not _LOCATION_COUNT.match(text):
        return text
    match = _PATH_LOCATION.match(record.get("externalPath") or "")
    if not match:
        return text or None
    # Path segments encode separators as hyphen runs: "India---Hyderabad".
    primary = re.sub(r"-{2,}", ", ", match.group(1)).replace("-", " ").strip()
    if not primary:
        return text or None
    return f"{primary} (+{text})" if text else primary


def _body(offset: int) -> dict:
    return {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": ""}


def _posted_date(record: dict, today: date | None = None) -> str | None:
    """Workday reports recency as prose — "Posted 5 Days Ago", "Posted Today",
    "Posted 30+ Days Ago" — never a timestamp. The derived date is therefore
    approximate, and anything at the "30+" ceiling is a floor rather than a
    real date, so it is left unset rather than reported as exactly 30 days old.
    """
    raw = record.get("postedOn") or ""
    today = today or date.today()
    if _POSTED_TODAY.search(raw):
        return today.isoformat()
    if _POSTED_YESTERDAY.search(raw):
        return (today - timedelta(days=1)).isoformat()
    match = _RELATIVE_DAYS.search(raw)
    if not match:
        return None
    if "+" in raw:
        return None
    return (today - timedelta(days=int(match.group(1)))).isoformat()


def _job_id(record: dict) -> str | None:
    """Prefer the requisition id Workday surfaces in bulletFields; it is the
    same id embedded in externalPath, and stays stable if the path slug (which
    contains the title) is edited."""
    for value in record.get("bulletFields") or []:
        if value:
            return str(value)
    path = record.get("externalPath") or ""
    match = re.search(r"_([A-Za-z0-9-]+)$", path)
    return match.group(1) if match else None


class WorkdayScraper(Scraper):
    """One parameterised scraper for every company on a public Workday board.

    Unlike Greenhouse and Ashby this endpoint only answers POST, so the config
    uses FetchMode.JSON_POST and each page URL carries its request body in a
    query parameter (see jobwatch.fetch.build_post_url).
    """

    def __init__(self, company: str, tenant: str, cluster: str, site: str):
        self.endpoint = API_URL.format(tenant=tenant, cluster=cluster, site=site)
        self.base_url = f"https://{tenant}.{cluster}.myworkdayjobs.com"
        self.site = site
        self.config = CompanyConfig(
            name=company,
            career_url=build_post_url(self.endpoint, _body(0)),
            fetch_mode=FetchMode.JSON_POST,
            max_pages=MAX_PAGES,
        )

    def parse(self, payload: str) -> list[Job]:
        records = json.loads(payload).get("jobPostings") or []
        jobs: list[Job] = []
        for record in records:
            job_id = _job_id(record)
            title = record.get("title")
            path = record.get("externalPath")
            if not (job_id and title and path):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=title.strip(),
                    # externalPath is site-relative; the public posting lives
                    # under the job board's own path, not the API's.
                    url=f"{self.base_url}/{self.site}{path}",
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        records = json.loads(payload).get("jobPostings") or []
        if len(records) < PAGE_SIZE:
            return None  # short page means the board is exhausted
        endpoint, body = split_post_url(current_url)
        return build_post_url(endpoint, _body(int(body.get("offset", 0)) + PAGE_SIZE))


def scrapers() -> list[WorkdayScraper]:
    return [
        WorkdayScraper(company, tenant, cluster, site)
        for company, (tenant, cluster, site) in BOARDS.items()
    ]
