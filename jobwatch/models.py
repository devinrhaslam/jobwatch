from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum


class FetchMode(Enum):
    STATIC = "static"
    RENDERED = "rendered"
    # Load a page in a browser and return the body of an API response it makes,
    # rather than its markup. For boards that answer the whole board in one XHR
    # but only to a real browser, this reads the clean JSON the page itself
    # consumes instead of scraping the DOM it renders from that JSON.
    RENDERED_XHR = "rendered_xhr"
    # A JSON API that only answers POST. The page's query string carries the
    # request parameters so a page still has a URL identity, which is what the
    # framework's pagination contract is built on.
    JSON_POST = "json_post"
    # The same, but the body is form-encoded rather than JSON. Some endpoints
    # reject a JSON body outright.
    FORM_POST = "form_post"


@dataclass(frozen=True)
class Job:
    company: str
    job_id: str
    title: str
    url: str
    location: str | None = None
    posted_date: str | None = None  # ISO 8601 date string, e.g. "2026-07-31"

    @staticmethod
    def stable_id(title: str, location: str | None, url: str) -> str:
        raw = f"{title}|{location or ''}|{url}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class CompanyConfig:
    name: str
    career_url: str
    fetch_mode: FetchMode
    wait_for_selector: str | None = None  # required when fetch_mode is RENDERED
    # Overrides the engine's default pagination ceiling. Boards that cap a page
    # at 20 results need a far higher ceiling to seed, while still stopping
    # after one or two pages on a normal run via the no-new-ids early stop.
    max_pages: int | None = None
    # Extra headers sent with every fetch for this company. Some boards gate
    # their API behind a header whose presence is checked but whose value is
    # not, which is a bot filter rather than real authentication.
    request_headers: dict[str, str] | None = None
    # Disables that early stop. It assumes newest-first ordering, so that a page
    # of entirely known jobs means everything beyond it is older and already
    # seen. Boards that do not order by recency violate the assumption and must
    # be read in full or new postings deep in the list are silently missed.
    paginate_fully: bool = False
    # Substring identifying the API response to capture; required when
    # fetch_mode is RENDERED_XHR.
    capture_response_url: str | None = None
    # Which browser engine renders this company. Chromium is the default, but a
    # board's bot filter may reject headless Chromium specifically while serving
    # headless Firefox the same page, so the engine is per-company.
    browser_engine: str = "chromium"

    def __post_init__(self) -> None:
        if self.fetch_mode is FetchMode.RENDERED and not self.wait_for_selector:
            raise ValueError(
                "wait_for_selector is required when fetch_mode is RENDERED"
            )
        if self.fetch_mode is FetchMode.RENDERED_XHR and not self.capture_response_url:
            raise ValueError(
                "capture_response_url is required when fetch_mode is RENDERED_XHR"
            )
        if self.browser_engine not in ("chromium", "firefox", "webkit"):
            raise ValueError(f"unknown browser_engine {self.browser_engine!r}")
        if self.max_pages is not None and self.max_pages < 1:
            raise ValueError("max_pages must be at least 1 when set")
