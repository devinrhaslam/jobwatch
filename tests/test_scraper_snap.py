import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.snap import SnapScraper

FIXTURE = Path(__file__).parent / "fixtures" / "snap_jobs.json"


@pytest.fixture(scope="module")
def snap_jobs():
    return SnapScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_the_whole_board_in_one_request(snap_jobs):
    assert len(snap_jobs) == 168
    assert len({j.job_id for j in snap_jobs}) == 168


def test_unwraps_the_elasticsearch_source_envelope(snap_jobs):
    assert all(j.title and j.url.startswith("https://") for j in snap_jobs)


def test_board_exposes_no_posting_date(snap_jobs):
    # Recency comes purely from snapshot diffing here, as with Meta.
    assert all(j.posted_date is None for j in snap_jobs)


def test_multiple_offices_are_joined_and_deduplicated():
    payload = json.dumps(
        {
            "body": [
                {
                    "_id": "R1",
                    "_source": {
                        "id": "R1",
                        "title": "Software Engineer",
                        "absolute_url": "https://x/1",
                        "offices": [
                            {"location": "New York"},
                            {"location": "Seattle"},
                            {"location": "New York"},
                        ],
                    },
                }
            ]
        }
    )
    assert SnapScraper().parse(payload)[0].location == "New York, Seattle"


def test_falls_back_to_primary_location():
    payload = json.dumps(
        {
            "body": [
                {
                    "_id": "R1",
                    "_source": {
                        "id": "R1",
                        "title": "Software Engineer",
                        "absolute_url": "https://x/1",
                        "offices": [],
                        "primary_location": "Los Angeles",
                    },
                }
            ]
        }
    )
    assert SnapScraper().parse(payload)[0].location == "Los Angeles"


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps(
        {
            "body": [
                {"_id": "R1", "_source": {"id": "R1", "title": "Kept", "absolute_url": "https://x/1"}},
                {"_id": "R2", "_source": {"id": "R2", "title": "No URL"}},
                {"_id": "R3", "_source": {"absolute_url": "https://x/3"}},
                "not-a-dict",
            ]
        }
    )
    assert [j.job_id for j in SnapScraper().parse(payload)] == ["R1"]


def test_empty_board_parses_to_no_jobs():
    assert SnapScraper().parse(json.dumps({"body": []})) == []


def test_scraper_is_a_single_plain_get():
    scraper = SnapScraper()
    assert scraper.config.fetch_mode is FetchMode.STATIC
    assert scraper.next_page_url("{}", scraper.config.career_url) is None
