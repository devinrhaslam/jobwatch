import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.eightfold import (
    BOARDS,
    MAX_PAGES,
    PAGE_SIZE,
    EightfoldScraper,
    scrapers,
)

FIXTURE = Path(__file__).parent / "fixtures" / "eightfold_netflix_jobs.json"


def _scraper():
    return EightfoldScraper("Netflix", "https://explore.jobs.netflix.net", "netflix.com")


@pytest.fixture(scope="module")
def netflix_jobs():
    return _scraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_a_full_page(netflix_jobs):
    assert len(netflix_jobs) == PAGE_SIZE
    assert len({j.job_id for j in netflix_jobs}) == PAGE_SIZE


def test_job_url_is_the_canonical_posting(netflix_jobs):
    for job in netflix_jobs:
        assert job.url.startswith("https://")
        assert "/api/" not in job.url  # the API path, not a page a human can open


def test_posted_date_comes_from_the_creation_timestamp(netflix_jobs):
    assert all(j.posted_date for j in netflix_jobs)
    assert all(len(j.posted_date) == 10 for j in netflix_jobs)


def test_update_timestamp_is_not_used_as_the_posting_date():
    # t_update moves whenever a posting is edited, so it would report a stale
    # listing as freshly posted.
    payload = json.dumps(
        {
            "positions": [
                {
                    "id": 1,
                    "name": "Software Engineer",
                    "canonicalPositionUrl": "https://x/1",
                    "t_update": 1780000000,
                }
            ]
        }
    )
    assert _scraper().parse(payload)[0].posted_date is None


def test_multiple_locations_are_joined_and_deduplicated():
    payload = json.dumps(
        {
            "positions": [
                {
                    "id": 1,
                    "name": "Software Engineer",
                    "canonicalPositionUrl": "https://x/1",
                    "locations": ["USA - Remote", "New York", "USA - Remote"],
                }
            ]
        }
    )
    assert _scraper().parse(payload)[0].location == "USA - Remote, New York"


def test_falls_back_to_the_single_location_field():
    payload = json.dumps(
        {
            "positions": [
                {
                    "id": 1,
                    "name": "Software Engineer",
                    "canonicalPositionUrl": "https://x/1",
                    "locations": [],
                    "location": "Los Angeles",
                }
            ]
        }
    )
    assert _scraper().parse(payload)[0].location == "Los Angeles"


def test_next_page_advances_the_start_offset(netflix_jobs):
    scraper = _scraper()
    nxt = scraper.next_page_url(FIXTURE.read_text(encoding="utf-8"), scraper.config.career_url)
    params = parse_qs(urlsplit(nxt).query)
    assert params["start"] == [str(PAGE_SIZE)]
    assert params["domain"] == ["netflix.com"]  # other params survive


def test_a_short_page_ends_pagination():
    scraper = _scraper()
    payload = json.dumps({"positions": [{"id": 1, "name": "x", "canonicalPositionUrl": "https://x/1"}]})
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps(
        {
            "positions": [
                {"id": 1, "name": "Kept", "canonicalPositionUrl": "https://x/1"},
                {"id": 2, "name": "No URL"},
                {"name": "No id", "canonicalPositionUrl": "https://x/3"},
                {"id": 4, "canonicalPositionUrl": "https://x/4"},
            ]
        }
    )
    assert [j.job_id for j in _scraper().parse(payload)] == ["1"]


def test_empty_board_parses_to_no_jobs():
    assert _scraper().parse(json.dumps({"positions": []})) == []


def test_board_is_read_in_full_because_it_is_not_ordered_by_recency():
    # Measured on Netflix's 481 postings, the 15 newest spanned pages 1-22 of
    # 49. The engine's no-new-ids early stop assumes newest-first ordering, so
    # relying on it here would silently drop new postings.
    scraper = _scraper()
    assert scraper.config.paginate_fully is True
    assert scraper.config.max_pages == MAX_PAGES
    assert MAX_PAGES * PAGE_SIZE >= 481


def test_scraper_is_a_plain_get():
    assert _scraper().config.fetch_mode is FetchMode.STATIC


def test_microsoft_is_not_registered():
    # Its Eightfold tenant answers 403 "Not authorized for PCSX" to the public
    # jobs API, so it cannot be served by this scraper.
    assert "Microsoft" not in BOARDS


def test_every_board_yields_a_distinct_registered_scraper():
    built = scrapers()
    assert len(built) == len(BOARDS)
    assert {s.config.name for s in built} == set(BOARDS)
    assert len({s.config.career_url for s in built}) == len(BOARDS)
