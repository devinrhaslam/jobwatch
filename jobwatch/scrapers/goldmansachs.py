from __future__ import annotations

import json
import re
from datetime import datetime

from jobwatch.fetch import build_post_url, split_post_url
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# higher.gs.com is a Next.js app that ships no listings in its HTML and whose
# `_next/data` payload is an empty Apollo cache, so the board only exists behind
# this GraphQL gateway. It needs no key, no cookie and no browser, and it leaves
# introspection enabled, which is how the query below was derived rather than
# guessed.
API_URL = "https://api-higher.gs.com/gateway/api/v1/graphql"

HOST = "https://higher.gs.com"
POSTING_URL = f"{HOST}/roles/{{role_number}}"

# 200 is the ceiling; 500 answers "Validation Exception."
PAGE_SIZE = 200
MAX_PAGES = 40

# Roles an outside applicant can actually take. INTERNAL_MOBILITY is open only
# to current employees, and CAMPUS is student hiring — including them would add
# ~150 postings that are noise for an experienced hire.
EXPERIENCES = ["PROFESSIONAL", "EARLY_CAREER"]

QUERY = """
query RoleSearch($searchQueryInput: RoleSearchQueryInput!) {
  roleSearch(searchQueryInput: $searchQueryInput) {
    totalCount
    items {
      roleId
      jobTitle
      lastPostedDate
      locations { city state country }
    }
  }
}
"""

# The role id carries a suffix — "180593_GS_MID_CAREER" — but the posting page
# is /roles/180593, so the URL needs the numeric part alone.
ROLE_NUMBER = re.compile(r"^(\d+)")


def _body(page_number: int) -> dict:
    return {
        "operationName": "RoleSearch",
        "variables": {
            "searchQueryInput": {
                "page": {"pageSize": PAGE_SIZE, "pageNumber": page_number},
                "experiences": EXPERIENCES,
                # Sorting newest-first is what makes the engine's early stop
                # safe on a 1,096-posting board.
                "sort": {"sortStrategy": "POSTED_DATE", "sortOrder": "DESC"},
            }
        },
        "query": QUERY,
    }


def _page_url(page_number: int) -> str:
    return build_post_url(API_URL, _body(page_number))


def _location(record: dict) -> str | None:
    names = []
    for entry in record.get("locations") or []:
        if not isinstance(entry, dict):
            continue
        parts = [entry.get("city"), entry.get("state"), entry.get("country")]
        name = ", ".join(str(p) for p in parts if p)
        if name and name not in names:
            names.append(name)
    return " | ".join(names) or None


def _posted_date(record: dict) -> str | None:
    raw = record.get("lastPostedDate")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _result(payload: str) -> dict:
    data = json.loads(payload).get("data") or {}
    return data.get("roleSearch") or {}


class GoldmanSachsScraper(Scraper):
    """Goldman Sachs' external board, read through the higher.gs.com gateway."""

    config = CompanyConfig(
        name="Goldman Sachs",
        career_url=_page_url(1),
        fetch_mode=FetchMode.JSON_POST,
        max_pages=MAX_PAGES,
    )

    def parse(self, payload: str) -> list[Job]:
        jobs: list[Job] = []
        for record in _result(payload).get("items") or []:
            if not isinstance(record, dict):
                continue
            role_id = record.get("roleId")
            title = record.get("jobTitle")
            if not (role_id and title):
                continue
            match = ROLE_NUMBER.match(str(role_id))
            if not match:
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(role_id),
                    title=str(title).strip(),
                    url=POSTING_URL.format(role_number=match.group(1)),
                    location=_location(record),
                    posted_date=_posted_date(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        """`totalCount` overstates the board and cannot be the stop condition:
        it reports 1,096 while pagination yields 896 rows and then a short page.
        The short page is what actually ends the walk; the total is kept only as
        a secondary ceiling so a board that never short-pages still terminates.
        """
        result = _result(payload)
        items = result.get("items") or []
        if len(items) < PAGE_SIZE:
            return None
        _, body = split_post_url(current_url)
        page = body["variables"]["searchQueryInput"]["page"]["pageNumber"]
        total = int(result.get("totalCount") or 0)
        if total and page * PAGE_SIZE >= total:
            return None
        return _page_url(page + 1)
