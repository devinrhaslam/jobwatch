from __future__ import annotations

import json
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Oracle Recruiting Cloud ("Candidate Experience"). Each tenant is a host plus a
# site name; the API is identical across them, so this is parameterised like the
# Greenhouse and Ashby scrapers.
API_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
POSTING_PATH = "/hcmUI/CandidateExperience/en/sites/{site}/job/{job_id}"

PAGE_SIZE = 200  # a larger limit is accepted but silently capped at 200
MAX_PAGES = 40

# The facet list is required: without it the response carries a job count but an
# empty requisitionList, which reads like an empty board rather than a bad query.
_FACETS = (
    "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;"
    "ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS"
)

# company -> (host, site name, siteNumber).
BOARDS = {
    "Uber": ("https://iaziqy.fa.ocs.oraclecloud.com", "UberCareers", "CX_1"),
}


def _page_url(host: str, site_number: str, offset: int) -> str:
    finder = (
        f"findReqs;siteNumber={site_number},facetsList={_FACETS},"
        f"limit={PAGE_SIZE},sortBy=POSTING_DATES_DESC,offset={offset}"
    )
    query = urlencode(
        {
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations,flexFieldsFacet.values",
            "finder": finder,
        }
    )
    return f"{host}{API_PATH}?{query}"


def _requisitions(payload: str) -> tuple[list[dict], int]:
    items = json.loads(payload).get("items") or []
    if not items or not isinstance(items[0], dict):
        return [], 0
    first = items[0]
    return (first.get("requisitionList") or []), int(first.get("TotalJobsCount") or 0)


def _location(record: dict) -> str | None:
    names = []
    primary = record.get("PrimaryLocation")
    if primary:
        names.append(str(primary))
    for extra in record.get("secondaryLocations") or []:
        name = extra.get("Name") if isinstance(extra, dict) else None
        if name and str(name) not in names:
            names.append(str(name))
    return " | ".join(names) or None


class OracleScraper(Scraper):
    """One parameterised scraper for companies on Oracle Recruiting Cloud.

    Job links point at the Oracle-hosted posting rather than the company's own
    careers domain. For Uber that is not a preference but a correctness issue:
    its uber.com and jobs.uber.com pages answer "the page you are looking for
    does not exist" for requisitions this API reports as live.
    """

    def __init__(self, company: str, host: str, site: str, site_number: str):
        self.host = host
        self.site = site
        self.site_number = site_number
        self.config = CompanyConfig(
            name=company,
            career_url=_page_url(host, site_number, 0),
            fetch_mode=FetchMode.STATIC,
            max_pages=MAX_PAGES,
        )

    def parse(self, payload: str) -> list[Job]:
        records, _ = _requisitions(payload)
        jobs: list[Job] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            job_id = record.get("Id")
            title = record.get("Title")
            if not (job_id and title):
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=self.host + POSTING_PATH.format(site=self.site, job_id=job_id),
                    location=_location(record),
                    posted_date=record.get("PostedDate") or None,
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        records, total = _requisitions(payload)
        if len(records) < PAGE_SIZE:
            return None  # a short page means the board is exhausted
        parsed = urlsplit(current_url)
        finder = parse_qs(parsed.query).get("finder", [""])[0]
        offset = 0
        for part in finder.split(","):
            if part.startswith("offset="):
                offset = int(part.split("=", 1)[1])
        offset += PAGE_SIZE
        if total and offset >= total:
            return None
        return _page_url(self.host, self.site_number, offset)


def scrapers() -> list[OracleScraper]:
    return [
        OracleScraper(company, host, site, site_number)
        for company, (host, site, site_number) in BOARDS.items()
    ]
