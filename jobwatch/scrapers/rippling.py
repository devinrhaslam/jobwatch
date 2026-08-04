from __future__ import annotations

import json

from jobwatch.fetch import build_post_url, split_post_url
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Rippling runs its own ATS product rather than using a third-party board, and
# its careers page has no server-rendered listings. The page searches an Algolia
# index instead. The application id and key below are Algolia's public,
# search-only credentials — served in plain sight to every visitor of the
# careers page, and usable only to read this one index.
ALGOLIA_APP_ID = "6FNAX3TBEF"
ALGOLIA_SEARCH_KEY = "416caa4690f002ff6fe4a2097623640b"
ALGOLIA_INDEX = "careers_en-US_production"

API_URL = f"https://{ALGOLIA_APP_ID.lower()}-dsn.algolia.net/1/indexes/*/queries"

# The index answers the whole board in one request at this size.
HITS_PER_PAGE = 1000
MAX_PAGES = 20

REQUEST_HEADERS = {
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "X-Algolia-API-Key": ALGOLIA_SEARCH_KEY,
}


def _body(page: int) -> dict:
    return {
        "requests": [
            {
                "indexName": ALGOLIA_INDEX,
                "query": "",
                "hitsPerPage": HITS_PER_PAGE,
                "page": page,
            }
        ]
    }


def _location(record: dict) -> str | None:
    names = [str(n) for n in (record.get("locationNames") or []) if n]
    if not names and record.get("locations"):
        names = [
            str(loc.get("name"))
            for loc in record["locations"]
            if isinstance(loc, dict) and loc.get("name")
        ]
    location = ", ".join(dict.fromkeys(names))
    # Many remote rows already name themselves "Remote (Dallas, Texas, US)", so
    # appending the flag unconditionally reads as "…, Remote, Remote".
    if record.get("isRemote") and "remote" not in location.lower():
        location = f"{location}, Remote" if location else "Remote"
    return location or None


def _result(payload: str) -> dict:
    results = json.loads(payload).get("results") or []
    return results[0] if results and isinstance(results[0], dict) else {}


class RipplingScraper(Scraper):
    """Rippling's careers board, read through the Algolia index its site searches.

    Postings carry no publication date, so recency comes from snapshot diffing.
    """

    config = CompanyConfig(
        name="Rippling",
        career_url=build_post_url(API_URL, _body(0)),
        fetch_mode=FetchMode.JSON_POST,
        max_pages=MAX_PAGES,
        request_headers=REQUEST_HEADERS,
    )

    def parse(self, payload: str) -> list[Job]:
        hits = _result(payload).get("hits") or []
        jobs: list[Job] = []
        for record in hits:
            if not isinstance(record, dict):
                continue
            # objectID is "<jobId>__<location-slug>": one requisition is indexed
            # once per location, so jobId repeats (395 distinct across 734 rows).
            # Keying on objectID keeps a role in San Antonio distinct from the
            # same role in Dublin, which matters because the report-time filter
            # judges location.
            job_id = record.get("objectID")
            title = record.get("name")
            url = record.get("url")
            if not (job_id and title and url):
                continue
            jobs.append(
                Job(
                    company="Rippling",
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=str(url),
                    location=_location(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        result = _result(payload)
        page = int(result.get("page") or 0)
        if page + 1 >= int(result.get("nbPages") or 0):
            return None
        endpoint, _ = split_post_url(current_url)
        return build_post_url(endpoint, _body(page + 1))
