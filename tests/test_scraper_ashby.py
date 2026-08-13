import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.ashby import BOARDS, GRAPHQL_BOARDS, AshbyScraper, scrapers

FIXTURE = Path(__file__).parent / "fixtures" / "ashby_linear_jobs.json"


@pytest.fixture(scope="module")
def linear_jobs():
    return AshbyScraper("Linear", "linear").parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(linear_jobs):
    assert len(linear_jobs) == 24
    assert len({j.job_id for j in linear_jobs}) == 24


def test_job_ids_are_the_board_uuids(linear_jobs):
    # Ashby keys on a UUID rather than an integer; the id must appear in the
    # job URL so a snapshot entry stays traceable back to the posting.
    job = linear_jobs[0]
    assert len(job.job_id) == 36 and job.job_id.count("-") == 4
    assert job.job_id in job.url


def test_posted_date_is_populated_from_published_at(linear_jobs):
    assert all(j.posted_date for j in linear_jobs)
    assert all(len(j.posted_date) == 10 for j in linear_jobs)  # YYYY-MM-DD


def test_secondary_locations_are_appended_to_the_primary():
    payload = json.dumps(
        {
            "jobs": [
                {
                    "id": "abc",
                    "title": "Software Engineer",
                    "jobUrl": "https://example.com/abc",
                    "location": "San Francisco",
                    "secondaryLocations": [
                        {"location": "New York City"},
                        {"location": "Seattle"},
                    ],
                }
            ]
        }
    )
    job = AshbyScraper("Acme", "acme").parse(payload)[0]
    assert job.location == "San Francisco, New York City, Seattle"


def test_duplicate_secondary_location_is_not_repeated():
    payload = json.dumps(
        {
            "jobs": [
                {
                    "id": "abc",
                    "title": "Software Engineer",
                    "jobUrl": "https://example.com/abc",
                    "location": "Remote",
                    "secondaryLocations": [{"location": "Remote"}],
                }
            ]
        }
    )
    assert AshbyScraper("Acme", "acme").parse(payload)[0].location == "Remote"


def test_unlisted_postings_are_skipped():
    payload = json.dumps(
        {
            "jobs": [
                {"id": "a", "title": "Listed", "jobUrl": "https://x/a", "isListed": True},
                {"id": "b", "title": "Hidden", "jobUrl": "https://x/b", "isListed": False},
                {"id": "c", "title": "Unflagged", "jobUrl": "https://x/c"},
            ]
        }
    )
    jobs = AshbyScraper("Acme", "acme").parse(payload)
    assert [j.job_id for j in jobs] == ["a", "c"]


def test_apply_url_is_used_when_job_url_is_absent():
    payload = json.dumps(
        {
            "jobs": [
                {
                    "id": "abc",
                    "title": "Software Engineer",
                    "applyUrl": "https://example.com/abc/application",
                }
            ]
        }
    )
    job = AshbyScraper("Acme", "acme").parse(payload)[0]
    assert job.url == "https://example.com/abc/application"


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps(
        {
            "jobs": [
                {"id": "a", "title": "Kept", "jobUrl": "https://x/a"},
                {"id": "b", "title": "No URL"},
                {"title": "No id", "jobUrl": "https://x/c"},
                {"id": "d", "jobUrl": "https://x/d"},
            ]
        }
    )
    assert [j.job_id for j in AshbyScraper("Acme", "acme").parse(payload)] == ["a"]


def test_empty_board_parses_to_no_jobs():
    assert AshbyScraper("Acme", "acme").parse(json.dumps({"jobs": []})) == []


def test_scraper_is_static_and_targets_the_posting_api():
    scraper = AshbyScraper("OpenAI", "openai")
    assert scraper.config.fetch_mode is FetchMode.STATIC
    assert scraper.config.career_url.endswith("/job-board/openai")


def test_every_board_yields_a_distinct_registered_scraper():
    # scrapers() covers both Ashby read paths: the public posting API, and the
    # board's own GraphQL endpoint for companies that have the posting API
    # switched off.
    expected = set(BOARDS) | set(GRAPHQL_BOARDS)
    built = scrapers()
    assert len(built) == len(expected)
    assert {s.config.name for s in built} == expected
    assert len({s.config.career_url for s in built}) == len(expected)
