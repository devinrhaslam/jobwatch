import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.amazon import PAGE_SIZE, AmazonScraper, _posted_date

FIXTURE = Path(__file__).parent / "fixtures" / "amazon_jobs.json"


@pytest.fixture(scope="module")
def amazon_jobs():
    return AmazonScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_a_full_page(amazon_jobs):
    assert len(amazon_jobs) == PAGE_SIZE
    assert len({j.job_id for j in amazon_jobs}) == PAGE_SIZE


def test_job_url_is_absolute(amazon_jobs):
    assert all(j.url.startswith("https://www.amazon.jobs/") for j in amazon_jobs)


def test_posted_date_parses_the_doubled_space_format():
    # Amazon pads single-digit days: "August  4, 2026".
    assert _posted_date({"posted_date": "August  4, 2026"}) == "2026-08-04"
    assert _posted_date({"posted_date": "December 15, 2025"}) == "2025-12-15"


def test_unparseable_posted_date_is_left_unset():
    assert _posted_date({"posted_date": "recently"}) is None
    assert _posted_date({}) is None


def test_entry_url_narrows_at_source_and_sorts_by_recency():
    # The full board is far larger than the target scope, and sort=recent is
    # what makes the engine's early stop safe.
    url = AmazonScraper.config.career_url
    assert "base_query=software+engineer" in url
    assert "sort=recent" in url


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps(
        {
            "jobs": [
                {"id_icims": "1", "title": "Kept", "job_path": "/en/jobs/1/kept"},
                {"id_icims": "2", "title": "No path"},
                {"title": "No id", "job_path": "/en/jobs/3/x"},
            ]
        }
    )
    assert [j.job_id for j in AmazonScraper().parse(payload)] == ["1"]


def test_pagination_stops_once_hits_are_exhausted():
    scraper = AmazonScraper()
    payload = json.dumps(
        {"jobs": [{"id_icims": str(i), "title": "x", "job_path": "/j"} for i in range(PAGE_SIZE)],
         "hits": PAGE_SIZE}
    )
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_pagination_advances_while_more_remain():
    scraper = AmazonScraper()
    payload = json.dumps(
        {"jobs": [{"id_icims": str(i), "title": "x", "job_path": "/j"} for i in range(PAGE_SIZE)],
         "hits": PAGE_SIZE * 5}
    )
    assert f"offset={PAGE_SIZE}" in scraper.next_page_url(payload, scraper.config.career_url)


def test_empty_board_parses_to_no_jobs():
    assert AmazonScraper().parse(json.dumps({"jobs": []})) == []


def test_scraper_is_a_plain_get():
    assert AmazonScraper.config.fetch_mode is FetchMode.STATIC
