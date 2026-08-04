from __future__ import annotations

import json

from jobwatch.fetch import build_post_url, split_post_url
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

API_URL = "https://jobs.bytedance.com/api/v1/public/supplier/search/job/posts"
POSTING_URL = "https://jobs.bytedance.com/en/position/{job_id}/detail"

PAGE_SIZE = 200
MAX_PAGES = 40

# The endpoint rejects everything with a bare `400 invalid request` until it
# receives this header — it selects the locale, and without it no payload shape
# works. The portal also sends `x-tt-env: boe_epam_api`, which is an internal
# environment selector and is deliberately not sent here: the request succeeds
# without it, and pinning ourselves to someone's test environment is a bad idea.
REQUEST_HEADERS = {"website-path": "en"}


def _body(offset: int) -> dict:
    # The empty list fields are required; the endpoint 400s without them.
    return {
        "recruitment_id_list": [],
        "job_category_id_list": [],
        "subject_id_list": [],
        "location_code_list": [],
        "keyword": "",
        "limit": PAGE_SIZE,
        "offset": offset,
    }


def _location(record: dict) -> str | None:
    """city_info nests city -> state -> country, each with a localised `name`
    and an English `en_name`. Walk the chain and keep the English names."""
    city = record.get("city_info")
    if not isinstance(city, dict):
        return None
    names: list[str] = []
    node: object = city
    while isinstance(node, dict):
        name = node.get("en_name") or node.get("name")
        if name and str(name) not in names:
            names.append(str(name))
        node = node.get("parent")
    if len(names) > 2:
        # Drop the middle administrative region; city and country are enough.
        names = [names[0], names[-1]]
    return ", ".join(names) or None


class ByteDanceScraper(Scraper):
    """ByteDance's careers API, as called by the joinbytedance.com portal.

    Postings carry a `publish_time` field but it is null on every record, so
    recency comes purely from snapshot diffing — and because that means
    newest-first ordering cannot be confirmed, the board is read in full.
    At 200 a page that is six requests.
    """

    config = CompanyConfig(
        name="ByteDance",
        career_url=build_post_url(API_URL, _body(0)),
        fetch_mode=FetchMode.JSON_POST,
        max_pages=MAX_PAGES,
        request_headers=REQUEST_HEADERS,
        paginate_fully=True,
    )

    def parse(self, payload: str) -> list[Job]:
        data = json.loads(payload).get("data") or {}
        records = data.get("job_post_list") or []
        jobs: list[Job] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            job_id = record.get("id")
            title = record.get("title")
            if not (job_id and title):
                continue
            jobs.append(
                Job(
                    company="ByteDance",
                    job_id=str(job_id),
                    title=str(title).strip(),
                    url=POSTING_URL.format(job_id=job_id),
                    location=_location(record),
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        data = json.loads(payload).get("data") or {}
        records = data.get("job_post_list") or []
        if len(records) < PAGE_SIZE:
            return None  # a short page means the board is exhausted
        endpoint, body = split_post_url(current_url)
        offset = int(body.get("offset", 0)) + PAGE_SIZE
        if offset >= int(data.get("count") or 0):
            return None
        return build_post_url(endpoint, _body(offset))
