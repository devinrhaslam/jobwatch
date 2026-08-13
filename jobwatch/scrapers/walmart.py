from __future__ import annotations

import json
from datetime import datetime, timezone

from jobwatch.fetch import build_post_url
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# ---------------------------------------------------------------------------
# NOTE: this endpoint is under the `Disallow: /api` that careers.walmart.com
# publishes. That is not what decides whether it is read — robots.txt is a
# crawler convention, and this project treats it as information rather than a
# gate (see the README). What matters here is the *load* argument below, and it
# happens to favour the disallowed path.
#
# The reasoning, for whoever revisits this: Walmart publishes no way to see only
# its technology roles. The permitted sitemap is 15,473 bare job URLs covering
# the whole company — no titles, no categories, no lastmod — so the compliant
# design is "store every id, then fetch a detail page per new posting", which is
# both mostly retail noise and *more* total load on Walmart than this is. This
# endpoint returns the 684 technology roles in a single request.
#
# If that trade ever stops being acceptable, delete this module and drop Walmart
# Global Tech from companies.txt; do not quietly fall back to the sitemap, which
# would flood every report with store and supply-chain jobs.
#
# Bloomberg, Intuit, Disney and Klarna read sitemaps and feeds rather than APIs
# for their own reasons — one request instead of dozens, or a published
# interface instead of an internal one — which are worth keeping on their
# merits, not because a robots file asked.
# ---------------------------------------------------------------------------
API_URL = "https://careers.walmart.com/api/ai/search-ai/api/v1/combined/hybrid-search"

HOST = "https://careers.walmart.com"
POSTING_URL = f"{HOST}/us/en/jobs/{{requisition}}"

# Filters are expressed inside the query string, not in the `filter` field —
# the site's own bundle builds `query + " brand IN [...]"` and always sends
# `filter: ""`. `areas IN [Technology]` is the same shape and is what narrows
# 15,473 company-wide postings to the technology arm.
QUERY = "areas IN [Technology]"

# The `page` parameter does not paginate: page 1 comes back holding page 0's
# rows. It does not need to. This is a relevance-scored search whose ordering
# shifts between calls, so a truncated read would return a different subset each
# run and the diff would report churn as new jobs — but asking for more than the
# board holds returns all of it, stably (two consecutive full reads differ by
# zero ids). So the board is always taken whole, in one request, and a response
# that comes back short is treated as an error rather than a smaller board.
PAGE_SIZE = 2000

REQUEST_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": HOST,
    "Referer": f"{HOST}/us/en/results",
}


def _body() -> dict:
    return {"query": QUERY, "basicSearch": False, "filter": "", "locale": "en_US"}


def _location(metadata: dict) -> str | None:
    """Cities arrive shouted ("BENTONVILLE"), which reads badly next to every
    other company in a report, so only the city is case-normalised — the state
    and country codes are already correct as capitals."""
    city = metadata.get("primaryLocationCity")
    parts = [
        str(city).title() if city else None,
        metadata.get("primaryLocationState"),
        metadata.get("primaryLocationCountry"),
    ]
    return ", ".join(str(p) for p in parts if p) or None


def _posted_date(metadata: dict) -> str | None:
    """`jobPostingStartDate` is epoch milliseconds and is the posting's start,
    not a re-index timestamp."""
    raw = metadata.get("jobPostingStartDate")
    if not isinstance(raw, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(raw / 1000, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _requisition(job_id: str) -> str:
    """Ids arrive as "R-2484821-External"; the posting page is /jobs/R-2484821."""
    return job_id.rsplit("-External", 1)[0]


class WalmartScraper(Scraper):
    """Walmart Global Tech — the technology slice of Walmart's board.

    Covers Walmart, Sam's Club and Vizio postings, which is what the technology
    career area spans; all three are Walmart-owned and all carry
    `areas: ["Technology"]`.
    """

    config = CompanyConfig(
        name="Walmart Global Tech",
        career_url=build_post_url(
            f"{API_URL}?page=0&size={PAGE_SIZE}&locale=en_US", _body()
        ),
        fetch_mode=FetchMode.JSON_POST,
        request_headers=REQUEST_HEADERS,
    )

    def parse(self, payload: str) -> list[Job]:
        body = json.loads(payload)
        records = body.get("jobs") or []
        total = body.get("totalJobs")
        if isinstance(total, int) and len(records) < total:
            # A short read is a different subset every time, not a smaller
            # board. Failing loudly beats letting the diff report the
            # difference between two arbitrary subsets as new jobs.
            raise ValueError(
                f"search returned {len(records)} of {total} technology jobs; "
                f"raise PAGE_SIZE above {PAGE_SIZE}"
            )
        jobs: list[Job] = []
        for record in records:
            raw_id = record.get("id")
            metadata = record.get("metadata") or {}
            title = metadata.get("title") or metadata.get("jobPostingTitle")
            if not (raw_id and title):
                continue
            requisition = _requisition(str(raw_id))
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=requisition,
                    title=str(title).strip(),
                    url=POSTING_URL.format(requisition=requisition),
                    location=_location(metadata),
                    posted_date=_posted_date(metadata),
                )
            )
        return jobs
