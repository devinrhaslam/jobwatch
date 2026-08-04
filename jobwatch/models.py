from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum


class FetchMode(Enum):
    STATIC = "static"
    RENDERED = "rendered"
    # A JSON API that only answers POST. The page's query string carries the
    # request parameters so a page still has a URL identity, which is what the
    # framework's pagination contract is built on.
    JSON_POST = "json_post"


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

    def __post_init__(self) -> None:
        if self.fetch_mode is FetchMode.RENDERED and not self.wait_for_selector:
            raise ValueError(
                "wait_for_selector is required when fetch_mode is RENDERED"
            )
        if self.max_pages is not None and self.max_pages < 1:
            raise ValueError("max_pages must be at least 1 when set")
