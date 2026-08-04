import json
from pathlib import Path

import pytest

from jobwatch.fetch import split_post_url
from jobwatch.models import FetchMode
from jobwatch.scrapers.bytedance import (
    PAGE_SIZE,
    REQUEST_HEADERS,
    ByteDanceScraper,
    _location,
)

FIXTURE = Path(__file__).parent / "fixtures" / "bytedance_jobs.json"


@pytest.fixture(scope="module")
def bytedance_jobs():
    return ByteDanceScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_a_full_page(bytedance_jobs):
    assert len(bytedance_jobs) == PAGE_SIZE
    assert len({j.job_id for j in bytedance_jobs}) == PAGE_SIZE


def test_job_url_points_at_the_public_posting(bytedance_jobs):
    for job in bytedance_jobs[:20]:
        assert job.url == f"https://jobs.bytedance.com/en/position/{job.job_id}/detail"


def test_every_posting_has_a_location(bytedance_jobs):
    assert all(j.location for j in bytedance_jobs)


def test_locale_header_is_sent():
    # Without it the endpoint rejects every payload with `400 invalid request`.
    assert REQUEST_HEADERS == {"website-path": "en"}
    assert ByteDanceScraper.config.request_headers == REQUEST_HEADERS


def test_internal_environment_header_is_not_sent():
    # The portal sends x-tt-env: boe_epam_api. The request succeeds without it,
    # and pinning to someone's test environment would be fragile.
    assert "x-tt-env" not in (ByteDanceScraper.config.request_headers or {})


def test_request_body_carries_the_required_empty_lists():
    # The endpoint 400s if these are absent.
    _, body = split_post_url(ByteDanceScraper.config.career_url)
    for key in ("recruitment_id_list", "job_category_id_list",
                "subject_id_list", "location_code_list"):
        assert body[key] == []
    assert body["offset"] == 0


def test_location_walks_the_city_country_chain():
    record = {"city_info": {"en_name": "San Jose", "parent": {
        "en_name": "California", "parent": {"en_name": "United States", "parent": None}}}}
    # The middle administrative region is dropped; city and country are enough.
    assert _location(record) == "San Jose, United States"


def test_location_prefers_english_names():
    record = {"city_info": {"name": "迪拜", "en_name": "Dubai", "parent": None}}
    assert _location(record) == "Dubai"


def test_location_falls_back_to_the_localised_name():
    record = {"city_info": {"name": "Shanghai", "parent": None}}
    assert _location(record) == "Shanghai"


def test_missing_city_info_yields_no_location():
    assert _location({}) is None


def test_board_exposes_no_posting_date(bytedance_jobs):
    # publish_time is present on every record but null on all of them.
    assert all(j.posted_date is None for j in bytedance_jobs)


def test_board_is_read_in_full_because_recency_cannot_be_confirmed():
    assert ByteDanceScraper.config.paginate_fully is True


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps({"data": {"job_post_list": [
        {"id": "1", "title": "Kept"},
        {"id": "2"},
        {"title": "No id"},
        "not-a-dict",
    ]}})
    assert [j.job_id for j in ByteDanceScraper().parse(payload)] == ["1"]


def test_empty_board_parses_to_no_jobs():
    assert ByteDanceScraper().parse(json.dumps({"data": {"job_post_list": []}})) == []


def test_a_short_page_ends_pagination():
    scraper = ByteDanceScraper()
    payload = json.dumps({"data": {"job_post_list": [{"id": "1", "title": "x"}], "count": 1}})
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_pagination_stops_once_the_count_is_reached():
    scraper = ByteDanceScraper()
    payload = json.dumps({"data": {
        "job_post_list": [{"id": str(i), "title": "x"} for i in range(PAGE_SIZE)],
        "count": PAGE_SIZE}})
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_pagination_advances_the_offset():
    scraper = ByteDanceScraper()
    payload = json.dumps({"data": {
        "job_post_list": [{"id": str(i), "title": "x"} for i in range(PAGE_SIZE)],
        "count": PAGE_SIZE * 4}})
    nxt = scraper.next_page_url(payload, scraper.config.career_url)
    _, body = split_post_url(nxt)
    assert body["offset"] == PAGE_SIZE


def test_scraper_uses_post_mode():
    assert ByteDanceScraper.config.fetch_mode is FetchMode.JSON_POST
