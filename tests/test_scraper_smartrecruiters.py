import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.smartrecruiters import (
    BOARDS,
    PAGE_SIZE,
    SmartRecruitersScraper,
    scrapers,
)

FIXTURE = Path(__file__).parent / "fixtures" / "smartrecruiters_canva_jobs.json"


def _scraper():
    return SmartRecruitersScraper("Canva", "canva")


@pytest.fixture(scope="module")
def canva_jobs():
    return _scraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_a_full_page(canva_jobs):
    assert len(canva_jobs) == PAGE_SIZE
    assert len({j.job_id for j in canva_jobs}) == PAGE_SIZE


def test_posting_url_is_built_from_identifier_and_id(canva_jobs):
    job = canva_jobs[0]
    assert job.url == f"https://jobs.smartrecruiters.com/Canva/{job.job_id}"


def test_posted_date_comes_from_released_date(canva_jobs):
    assert all(j.posted_date and len(j.posted_date) == 10 for j in canva_jobs)


def test_empty_location_segments_are_dropped():
    # The API renders a missing region as an empty segment: "Sydney, , Australia".
    payload = json.dumps(
        {
            "content": [
                {
                    "id": "1",
                    "name": "Software Engineer",
                    "company": {"identifier": "Canva"},
                    "location": {"fullLocation": "Sydney, , Australia"},
                }
            ]
        }
    )
    assert _scraper().parse(payload)[0].location == "Sydney, Australia"


def test_remote_is_appended_when_there_is_no_full_location():
    payload = json.dumps(
        {
            "content": [
                {
                    "id": "1",
                    "name": "Software Engineer",
                    "company": {"identifier": "Canva"},
                    "location": {"city": "Austin", "country": "us", "remote": True},
                }
            ]
        }
    )
    assert _scraper().parse(payload)[0].location == "Austin, us, Remote"


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps(
        {
            "content": [
                {"id": "1", "name": "Kept", "company": {"identifier": "Canva"}},
                {"id": "2", "name": "No identifier", "company": {}},
                {"name": "No id", "company": {"identifier": "Canva"}},
            ]
        }
    )
    assert [j.job_id for j in _scraper().parse(payload)] == ["1"]


def test_pagination_stops_once_the_total_is_reached():
    scraper = _scraper()
    payload = json.dumps(
        {"content": [{"id": str(i), "name": "x", "company": {"identifier": "Canva"}}
                     for i in range(PAGE_SIZE)], "totalFound": PAGE_SIZE}
    )
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_pagination_advances_while_more_remain():
    scraper = _scraper()
    payload = json.dumps(
        {"content": [{"id": str(i), "name": "x", "company": {"identifier": "Canva"}}
                     for i in range(PAGE_SIZE)], "totalFound": PAGE_SIZE * 3}
    )
    nxt = scraper.next_page_url(payload, scraper.config.career_url)
    assert f"offset={PAGE_SIZE}" in nxt


def test_a_short_page_ends_pagination():
    scraper = _scraper()
    payload = json.dumps({"content": [], "totalFound": 0})
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_scraper_is_a_plain_get():
    assert _scraper().config.fetch_mode is FetchMode.STATIC


def test_every_board_yields_a_distinct_registered_scraper():
    built = scrapers()
    assert {s.config.name for s in built} == set(BOARDS)
    assert len({s.config.career_url for s in built}) == len(BOARDS)
