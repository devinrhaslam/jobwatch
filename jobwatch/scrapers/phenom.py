from __future__ import annotations

import json
import re

from jobwatch.fetch import build_post_url, split_post_url
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

# Phenom career sites run on the company's own careers subdomain and answer
# their board from one POST endpoint, the same call the search page makes.
API_URL = "https://{host}/widgets"

# Posting pages live under a locale path. Both segments are fixed here rather
# than per company: they name the site's own default locale, not the jobs, and
# the board this reads is the whole board regardless of which locale asks for it
# — `country`, `global` and `siteType` in the request body all leave the result
# set at exactly the same postings.
LOCALE_PATH = "us/en"
JOB_URL = "https://{host}/" + LOCALE_PATH + "/job/{seq}/{slug}"

# The endpoint has no default page size — omitting `size` returns zero rows —
# and honours whatever it is given, so the whole board arrives in one request
# for a tenant of this size.
PAGE_SIZE = 100

# Enough pages to seed a board far larger than any tracked here.
MAX_PAGES = 40

# company -> careers host.
BOARDS = {
    # Circle's board was read from its Workday tenant until that tenant was
    # retired: circle.wd1.myworkdayjobs.com now answers 401 to the CXS API for
    # every site name, and its posting pages redirect to Workday's maintenance
    # page, so every link it ever produced is dead. The Phenom site in front of
    # it is the live board. Note that this reverses the reasoning recorded on
    # the Workday entry — reading Phenom was avoided precisely because its
    # records carry no posting URL of their own, only an applyUrl pointing back
    # at Workday. That is still true; the URL is built from `jobSeqNo` instead,
    # and verified against the sitemap below.
    "Circle": "careers.circle.com",
}

# Slugs collapse every run of non-alphanumerics to a single hyphen: "Senior
# Analyst, AML/Know Your Customer" becomes "Senior-Analyst-AML-Know-Your-
# Customer". Built rather than read because the listing carries no posting URL.
_SLUG_SEPARATORS = re.compile(r"[^A-Za-z0-9]+")


def _slug(title: str) -> str:
    return _SLUG_SEPARATORS.sub("-", title).strip("-")


def _job_url(host: str, record: dict) -> str | None:
    """The posting's page on the careers site.

    `jobSeqNo` is what the router keys on — the slug is decorative, so a title
    edited after this link was stored still resolves — and a retired posting
    answers 410 rather than silently rendering the whole listing.

    All 74 URLs built this way were checked byte-for-byte against the 74 job
    URLs in the sitemap that robots.txt publishes, which is the site's own
    statement of the canonical link.
    """
    seq = record.get("jobSeqNo")
    title = record.get("title")
    if not (seq and title):
        return None
    slug = _slug(str(title))
    if not slug:
        return None
    return JOB_URL.format(host=host, seq=seq, slug=slug)


def _location(record: dict) -> str | None:
    """The primary location, noting how many others the posting also lists.

    `isMultiLocation` is not the field to ask: it is False on postings carrying
    25 locations. The `multi_location` list is the honest count, and its first
    entry is the same string as `location` on every posting here.
    """
    primary = (record.get("location") or "").strip()
    if not primary:
        return None
    others = len(record.get("multi_location") or []) - 1
    return f"{primary} (+{others} locations)" if others > 0 else primary


def _posted_date(record: dict) -> str | None:
    """`postedDate` is a real publication date, not the moment of the fetch: it
    takes 43 distinct values across 74 postings spanning April to August. The
    field is an ISO timestamp; only the date part is kept."""
    raw = record.get("postedDate")
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    return raw[:10]


def _body(offset: int) -> dict:
    """The smallest body the endpoint answers.

    `ddoKey`, `jobs` and `size` are each load-bearing — dropping any one of them
    returns an empty result set with a 200 — while `deviceType`, `lang`,
    `pageName`, `country`, `global` and `siteType` were all verified inert and
    are left out rather than carried as cargo.
    """
    return {"ddoKey": "refineSearch", "jobs": True, "size": PAGE_SIZE, "from": offset}


def _search(payload: str) -> dict:
    return (json.loads(payload).get("refineSearch") or {})


def _records(payload: str) -> list[dict]:
    return (_search(payload).get("data") or {}).get("jobs") or []


class PhenomScraper(Scraper):
    """One parameterised scraper for companies on a public Phenom career site.

    The board is not ordered by recency — it comes back in the same order
    whatever `sortBy` asks for, and that order is not by `postedDate` — so this
    sets `paginate_fully` rather than relying on the engine's newest-first early
    stop, which would miss anything posted deeper in the list.
    """

    def __init__(self, company: str, host: str):
        self.host = host
        self.config = CompanyConfig(
            name=company,
            career_url=build_post_url(API_URL.format(host=host), _body(0)),
            fetch_mode=FetchMode.JSON_POST,
            max_pages=MAX_PAGES,
            paginate_fully=True,
        )

    def parse(self, payload: str) -> list[Job]:
        jobs: list[Job] = []
        for record in _records(payload):
            job_id = record.get("jobId") or record.get("reqId")
            title = record.get("title")
            url = _job_url(self.host, record)
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
        """Stop on the count rather than on a short page.

        A page shorter than PAGE_SIZE is the usual exhaustion signal, but it
        would also be what a server-side cap below the requested size looks
        like — and reading that as "board finished" is how a seed truncates
        quietly. `totalHits` is checked instead: it reported exactly the 74
        postings the sitemap lists, so it is a real total here.
        """
        records = _records(payload)
        if not records:
            return None
        endpoint, body = split_post_url(current_url)
        seen = int(body.get("from", 0)) + len(records)
        total = _search(payload).get("totalHits")
        if isinstance(total, int) and seen >= total:
            return None
        return build_post_url(endpoint, _body(seen))


def scrapers() -> list[PhenomScraper]:
    return [PhenomScraper(company, host) for company, host in BOARDS.items()]
