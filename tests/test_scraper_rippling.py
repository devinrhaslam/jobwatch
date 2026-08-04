import json
from pathlib import Path

import pytest

from jobwatch.fetch import split_post_url
from jobwatch.models import FetchMode
from jobwatch.scrapers.rippling import (
    ALGOLIA_INDEX,
    HITS_PER_PAGE,
    REQUEST_HEADERS,
    RipplingScraper,
    _location,
)

FIXTURE = Path(__file__).parent / "fixtures" / "rippling_jobs.json"


@pytest.fixture(scope="module")
def rippling_jobs():
    return RipplingScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_the_whole_board_in_one_request(rippling_jobs):
    assert len(rippling_jobs) == 734
    assert len({j.job_id for j in rippling_jobs}) == 734


def test_job_id_is_the_per_location_object_id(rippling_jobs):
    # objectID is "<jobId>__<location-slug>"; jobId alone repeats across
    # locations (395 distinct across 734 rows) and would collapse real rows.
    assert all("__" in j.job_id for j in rippling_jobs)


def test_job_url_points_at_the_ats_posting(rippling_jobs):
    assert all(j.url.startswith("https://ats.rippling.com/rippling/jobs/") for j in rippling_jobs)


def test_every_row_has_a_location(rippling_jobs):
    assert all(j.location for j in rippling_jobs)


def test_remote_flag_is_appended_once():
    assert _location({"locationNames": ["San Antonio, TX"], "isRemote": True}) == "San Antonio, TX, Remote"


def test_remote_flag_is_not_duplicated_when_the_name_already_says_remote():
    got = _location({"locationNames": ["Remote (Dallas, Texas, US)"], "isRemote": True})
    assert got == "Remote (Dallas, Texas, US)"


def test_location_falls_back_to_the_structured_locations():
    got = _location({"locationNames": [], "locations": [{"name": "Dublin, Ireland"}]})
    assert got == "Dublin, Ireland"


def test_remote_only_row_is_labelled_remote():
    assert _location({"locationNames": [], "isRemote": True}) == "Remote"


def test_missing_location_yields_none():
    assert _location({}) is None


def test_search_only_credentials_are_sent():
    assert set(REQUEST_HEADERS) == {"X-Algolia-Application-Id", "X-Algolia-API-Key"}
    assert RipplingScraper.config.request_headers == REQUEST_HEADERS


def test_request_targets_the_careers_index():
    _, body = split_post_url(RipplingScraper.config.career_url)
    request = body["requests"][0]
    assert request["indexName"] == ALGOLIA_INDEX
    assert request["hitsPerPage"] == HITS_PER_PAGE
    assert request["page"] == 0


def test_board_exposes_no_posting_date(rippling_jobs):
    assert all(j.posted_date is None for j in rippling_jobs)


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps({"results": [{"hits": [
        {"objectID": "a__x", "name": "Kept", "url": "https://x/a"},
        {"objectID": "b__x", "name": "No URL"},
        {"name": "No id", "url": "https://x/c"},
        "not-a-dict",
    ]}]})
    assert [j.job_id for j in RipplingScraper().parse(payload)] == ["a__x"]


def test_empty_board_parses_to_no_jobs():
    assert RipplingScraper().parse(json.dumps({"results": [{"hits": []}]})) == []


def test_unexpected_payload_shape_parses_to_no_jobs():
    assert RipplingScraper().parse(json.dumps({"results": []})) == []


def test_a_complete_response_ends_pagination(rippling_jobs):
    scraper = RipplingScraper()
    assert scraper.next_page_url(FIXTURE.read_text(encoding="utf-8"), scraper.config.career_url) is None


def test_pagination_advances_while_pages_remain():
    scraper = RipplingScraper()
    payload = json.dumps({"results": [{"hits": [], "page": 0, "nbPages": 3}]})
    nxt = scraper.next_page_url(payload, scraper.config.career_url)
    _, body = split_post_url(nxt)
    assert body["requests"][0]["page"] == 1


def test_scraper_uses_post_mode():
    assert RipplingScraper.config.fetch_mode is FetchMode.JSON_POST
