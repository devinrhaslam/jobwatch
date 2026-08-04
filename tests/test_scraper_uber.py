import json
from pathlib import Path

import pytest

from jobwatch.fetch import split_post_url
from jobwatch.models import FetchMode
from jobwatch.scrapers.uber import REQUEST_HEADERS, UberScraper, _location, _posted_date

FIXTURE = Path(__file__).parent / "fixtures" / "uber_jobs.json"


@pytest.fixture(scope="module")
def uber_jobs():
    return UberScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_the_whole_board_in_one_request(uber_jobs):
    assert len(uber_jobs) == 649
    assert len({j.job_id for j in uber_jobs}) == 649


def test_every_posting_is_dated(uber_jobs):
    assert all(j.posted_date and len(j.posted_date) == 10 for j in uber_jobs)


def test_job_url_points_at_the_public_posting(uber_jobs):
    for job in uber_jobs[:20]:
        assert job.url == f"https://www.uber.com/careers/list/{job.job_id}/"


def test_request_body_omits_limit():
    # Supplying `limit` caps the response; omitting it returns the whole board.
    _, body = split_post_url(UberScraper.config.career_url)
    assert "limit" not in body
    assert body["page"] == 0


def test_csrf_header_is_sent():
    # The endpoint answers 403 without it, but accepts any value.
    assert "x-csrf-token" in REQUEST_HEADERS
    assert UberScraper.config.request_headers == REQUEST_HEADERS


def test_multiple_locations_are_joined_and_deduplicated():
    record = {
        "allLocations": [
            {"city": "Melbourne", "countryName": "Australia"},
            {"city": "Sydney", "countryName": "Australia"},
            {"city": "Melbourne", "countryName": "Australia"},
        ]
    }
    assert _location(record) == "Melbourne, Australia | Sydney, Australia"


def test_falls_back_to_the_single_location():
    record = {"allLocations": [], "location": {"city": "Bangalore", "countryName": "India"}}
    assert _location(record) == "Bangalore, India"


def test_missing_location_yields_none():
    assert _location({"allLocations": []}) is None


def test_posted_date_parses_the_creation_timestamp():
    assert _posted_date({"creationDate": "2026-07-27T15:12:27.000Z"}) == "2026-07-27"


def test_updated_date_is_not_used_as_a_posting_date():
    # updatedDate moves whenever a posting is edited.
    assert _posted_date({"updatedDate": "2026-07-21T17:03:32.000Z"}) is None


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps(
        {"data": {"results": [
            {"id": 1, "title": "Kept"},
            {"id": 2},
            {"title": "No id"},
        ]}}
    )
    assert [j.job_id for j in UberScraper().parse(payload)] == ["1"]


def test_empty_board_parses_to_no_jobs():
    assert UberScraper().parse(json.dumps({"data": {"results": []}})) == []


def test_a_complete_response_ends_pagination(uber_jobs):
    scraper = UberScraper()
    assert scraper.next_page_url(FIXTURE.read_text(encoding="utf-8"), scraper.config.career_url) is None


def test_a_capped_response_paginates_as_a_safety_net():
    scraper = UberScraper()
    payload = json.dumps(
        {"data": {"results": [{"id": i, "title": "x"} for i in range(100)],
                  "totalResults": {"low": 649}}}
    )
    nxt = scraper.next_page_url(payload, scraper.config.career_url)
    _, body = split_post_url(nxt)
    assert body["page"] == 1


def test_scraper_uses_post_mode():
    assert UberScraper.config.fetch_mode is FetchMode.JSON_POST
