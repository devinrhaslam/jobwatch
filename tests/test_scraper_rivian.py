import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.rivian import PAGE_SIZE, RivianScraper

# One real page of the board. The description, responsibilities and
# qualifications bodies — which the scraper never reads — are replaced with a
# placeholder, taking the fixture from 1.9 MB to 655 KB.
FIXTURE = Path(__file__).parent / "fixtures" / "rivian_jobs.json"


@pytest.fixture(scope="module")
def payload():
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def jobs(payload):
    return RivianScraper().parse(payload)


def test_parses_a_full_page(jobs):
    assert len(jobs) == PAGE_SIZE
    assert len({j.job_id for j in jobs}) == PAGE_SIZE


def test_records_are_unwrapped_from_the_data_envelope(jobs):
    # The response is {"jobs": [{"data": {...}}]}. Reading the wrapper instead
    # of `data` yields a page of empty jobs rather than an error.
    assert all(j.title for j in jobs)
    assert all(j.job_id for j in jobs)


def test_url_is_the_public_posting_not_the_icims_login(jobs):
    assert all(
        j.url.startswith("https://careers.rivian.com/careers-home/jobs/") for j in jobs
    )
    assert not any("icims" in j.url or j.url.endswith("/login") for j in jobs)
    assert all(j.url.endswith(f"/{j.job_id}") for j in jobs)


def test_location_and_posted_date_are_populated(jobs):
    assert all(j.location for j in jobs)
    assert all(j.posted_date and len(j.posted_date) == 10 for j in jobs)


def test_posted_date_comes_from_posted_date_not_update_date():
    payload = _payload(
        [{"req_id": "1", "title": "Engineer",
          "posted_date": "2026-07-01T10:00:00+0000",
          "update_date": "2026-08-05T10:00:00+0000"}]
    )
    assert RivianScraper().parse(payload)[0].posted_date == "2026-07-01"


def test_location_falls_back_to_city_state_country():
    payload = _payload(
        [{"req_id": "1", "title": "Engineer", "city": "Irvine",
          "state": "California", "country": "United States"}]
    )
    assert RivianScraper().parse(payload)[0].location == "Irvine, California, United States"


def test_full_location_is_preferred_when_present():
    payload = _payload(
        [{"req_id": "1", "title": "Engineer", "full_location": "Irvine, California",
          "city": "Irvine", "state": "California"}]
    )
    assert RivianScraper().parse(payload)[0].location == "Irvine, California"


def test_unparseable_posted_date_leaves_it_unset():
    payload = _payload([{"req_id": "1", "title": "Engineer", "posted_date": "yesterday"}])
    assert RivianScraper().parse(payload)[0].posted_date is None


def test_records_without_id_or_title_are_skipped():
    payload = _payload(
        [{"title": "No id"}, {"req_id": "2"}, {"req_id": "3", "title": "Good"}]
    )
    assert [j.job_id for j in RivianScraper().parse(payload)] == ["3"]


def test_slug_is_used_when_req_id_is_missing():
    payload = _payload([{"slug": "999", "title": "Engineer"}])
    assert RivianScraper().parse(payload)[0].job_id == "999"


def test_a_full_page_asks_for_the_next_one(payload):
    nxt = RivianScraper().next_page_url(payload, _page_url(1))
    assert nxt is not None and "page=2" in nxt and f"limit={PAGE_SIZE}" in nxt


def test_a_short_page_ends_pagination():
    payload = _payload([{"req_id": "1", "title": "Engineer"}], total=630)
    assert RivianScraper().next_page_url(payload, _page_url(1)) is None


def test_pagination_stops_once_the_total_is_reached():
    full = _payload([{"req_id": str(i), "title": "T"} for i in range(PAGE_SIZE)], total=200)
    assert RivianScraper().next_page_url(full, _page_url(2)) is None


def test_config_requests_a_date_sorted_first_page():
    config = RivianScraper().config
    assert config.name == "Rivian"
    assert config.fetch_mode is FetchMode.STATIC
    # The early stop is only safe because the board is ordered newest-first.
    assert "sortBy=posted_date" in config.career_url
    assert "descending=true" in config.career_url
    assert f"limit={PAGE_SIZE}" in config.career_url


def _payload(records, total=None):
    return json.dumps(
        {"jobs": [{"data": r} for r in records], "totalCount": total or len(records)}
    )


def _page_url(page):
    from jobwatch.scrapers.rivian import _page_url as build

    return build(page)
