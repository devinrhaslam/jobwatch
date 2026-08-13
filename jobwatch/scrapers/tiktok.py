from __future__ import annotations

import json

from jobwatch.fetch import build_post_url, split_post_url
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper
# PAGE_SIZE comes from there too rather than being restated: `_body` bakes it in
# as the request's `limit`, so a local copy that drifted from it would make the
# short-page check below stop paginating a page early, or never at all.
from jobwatch.scrapers.bytedance import PAGE_SIZE, _body, _location

API_URL = "https://lifeattiktok.com/api/v1/public/supplier/search/job/posts"

# The posting's own page. `/position/{id}/detail` — the path ByteDance's portal
# uses — exists here too but only 302s to this one. A retired or invented id
# still answers 200 because the page is a shell, but it renders no <title>,
# while a live id renders the posting's title, so the link is a real deep link
# rather than a search page that happens to load.
POSTING_URL = "https://lifeattiktok.com/search/{job_id}"

# The board runs to ~3,970 postings, so a full read is twenty requests. Double
# that leaves room to grow without the ceiling silently truncating a seed.
MAX_PAGES = 40

# Same locale gate as ByteDance's portal, keyed to this site rather than a
# language: without it the endpoint answers a bare `invalid request`. The value
# is the site's own path segment, "tiktok" — ByteDance's "en" is rejected here.
REQUEST_HEADERS = {"website-path": "tiktok"}


class TikTokScraper(Scraper):
    """TikTok's careers API, as called by the lifeattiktok.com portal.

    Same recruitment platform as ByteDance's own board — identical request
    body, identical record shape — on a different host behind a different
    `website-path`, so the body builder and the `city_info` walk are shared
    with that module rather than copied.

    The two boards are nonetheless distinct rather than one board served twice:
    ByteDance's carries 1,311 postings to this one's 3,967, and a page of 200
    from each shares a single id. That one posting will be reported under both
    names, which is the honest reading — it is genuinely cross-posted.

    As on ByteDance's board `publish_time` is null on every record, so recency
    comes purely from snapshot diffing. Ids do descend across a page, but
    nothing in the payload states the ordering, so the board is read in full
    rather than trusting an undocumented sort for the engine's early stop.
    """

    config = CompanyConfig(
        name="TikTok",
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
                    company="TikTok",
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
