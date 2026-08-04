import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.oracle import (
    BOARDS,
    PAGE_SIZE,
    OracleScraper,
    _location,
    scrapers,
)

FIXTURE = Path(__file__).parent / "fixtures" / "oracle_uber_jobs.json"


def _scraper():
    return OracleScraper("Uber", "https://iaziqy.fa.ocs.oraclecloud.com", "UberCareers", "CX_1")


@pytest.fixture(scope="module")
def uber_jobs():
    return _scraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_a_full_page(uber_jobs):
    assert len(uber_jobs) == PAGE_SIZE
    assert len({j.job_id for j in uber_jobs}) == PAGE_SIZE


def test_every_posting_is_dated(uber_jobs):
    assert all(j.posted_date and len(j.posted_date) == 10 for j in uber_jobs)


def test_job_link_points_at_the_oracle_posting(uber_jobs):
    # Uber's own careers domains answer "does not exist" for requisitions this
    # API reports as live, so the Oracle-hosted page is the only working link.
    for job in uber_jobs[:20]:
        assert job.url.endswith(f"/sites/UberCareers/job/{job.job_id}")
        assert "uber.com" not in job.url


def _finder(url: str) -> str:
    return parse_qs(urlsplit(url).query)["finder"][0]


def test_entry_url_requests_newest_first():
    # Cards are ordered by posting date, which is what makes the engine's
    # no-new-ids early stop safe here.
    assert "sortBy=POSTING_DATES_DESC" in _finder(_scraper().config.career_url)


def test_entry_url_carries_the_facet_list():
    # Without it the response reports a job count but an empty requisitionList,
    # which reads like an empty board rather than a malformed query.
    assert "facetsList=LOCATIONS" in _finder(_scraper().config.career_url)


def test_secondary_locations_are_appended():
    payload = json.dumps({"items": [{"TotalJobsCount": 1, "requisitionList": [
        {"Id": "1", "Title": "SWE", "PrimaryLocation": "San Francisco",
         "secondaryLocations": [{"Name": "New York"}, {"Name": "San Francisco"}]}]}]})
    assert _scraper().parse(payload)[0].location == "San Francisco | New York"


def test_missing_location_yields_none():
    assert _location({}) is None


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps({"items": [{"TotalJobsCount": 3, "requisitionList": [
        {"Id": "1", "Title": "Kept"},
        {"Id": "2"},
        {"Title": "No id"},
        "not-a-dict",
    ]}]})
    assert [j.job_id for j in _scraper().parse(payload)] == ["1"]


def test_empty_board_parses_to_no_jobs():
    payload = json.dumps({"items": [{"TotalJobsCount": 0, "requisitionList": []}]})
    assert _scraper().parse(payload) == []


def test_unexpected_payload_shape_parses_to_no_jobs():
    assert _scraper().parse(json.dumps({"items": []})) == []


def test_a_short_page_ends_pagination():
    payload = json.dumps({"items": [{"TotalJobsCount": 1, "requisitionList": [
        {"Id": "1", "Title": "x"}]}]})
    scraper = _scraper()
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_pagination_stops_once_the_total_is_reached():
    payload = json.dumps({"items": [{"TotalJobsCount": PAGE_SIZE, "requisitionList": [
        {"Id": str(i), "Title": "x"} for i in range(PAGE_SIZE)]}]})
    scraper = _scraper()
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_pagination_advances_the_offset():
    payload = json.dumps({"items": [{"TotalJobsCount": PAGE_SIZE * 4, "requisitionList": [
        {"Id": str(i), "Title": "x"} for i in range(PAGE_SIZE)]}]})
    scraper = _scraper()
    nxt = scraper.next_page_url(payload, scraper.config.career_url)
    assert f"offset={PAGE_SIZE}" in _finder(nxt)


def test_scraper_is_a_plain_get():
    assert _scraper().config.fetch_mode is FetchMode.STATIC


def test_every_board_yields_a_distinct_registered_scraper():
    built = scrapers()
    assert {s.config.name for s in built} == set(BOARDS)
    assert len({s.config.career_url for s in built}) == len(BOARDS)
