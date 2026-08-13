import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.workable import BOARDS, WorkableScraper, scrapers

FIXTURE = Path(__file__).parent / "fixtures" / "workable_huggingface_jobs.json"


@pytest.fixture(scope="module")
def huggingface_jobs():
    return WorkableScraper("Hugging Face", "huggingface").parse(
        FIXTURE.read_text(encoding="utf-8")
    )


def test_parses_every_posting_in_the_fixture(huggingface_jobs):
    assert len(huggingface_jobs) == 7
    assert len({j.job_id for j in huggingface_jobs}) == 7


def test_job_id_is_the_shortcode_and_appears_in_the_url(huggingface_jobs):
    # The shortcode is what the posting URL is keyed on, so a snapshot entry
    # stays traceable back to the listing it came from.
    for job in huggingface_jobs:
        assert job.job_id in job.url


def test_url_is_the_posting_page_not_the_apply_form(huggingface_jobs):
    assert all(j.url.startswith("https://apply.workable.com/j/") for j in huggingface_jobs)
    assert not any(j.url.endswith("/apply") for j in huggingface_jobs)


def test_posted_date_comes_from_published_on(huggingface_jobs):
    assert all(j.posted_date for j in huggingface_jobs)
    assert all(len(j.posted_date) == 10 for j in huggingface_jobs)  # YYYY-MM-DD


def test_location_is_built_from_the_parts_because_location_is_null():
    # Every posting seen carries `location: null` and puts the place in city /
    # state / country. Reading `location` would blank the location board-wide.
    payload = json.dumps(
        {
            "jobs": [
                {
                    "shortcode": "AAA",
                    "title": "Engineer",
                    "url": "https://apply.workable.com/j/AAA",
                    "location": None,
                    "city": "Paris",
                    "state": "Île-de-France",
                    "country": "France",
                }
            ]
        }
    )
    (job,) = WorkableScraper("Test Co", "test").parse(payload)
    assert job.location == "Paris, Île-de-France, France"


def test_telecommuting_postings_are_marked_remote():
    payload = json.dumps(
        {
            "jobs": [
                {
                    "shortcode": "AAA",
                    "title": "Engineer",
                    "url": "https://apply.workable.com/j/AAA",
                    "city": "Paris",
                    "telecommuting": True,
                },
                {
                    "shortcode": "BBB",
                    "title": "Engineer",
                    "url": "https://apply.workable.com/j/BBB",
                    "telecommuting": True,
                },
            ]
        }
    )
    remote_with_place, remote_only = WorkableScraper("Test Co", "test").parse(payload)
    assert remote_with_place.location == "Paris (Remote)"
    assert remote_only.location == "Remote"


def test_records_missing_an_id_title_or_url_are_skipped():
    payload = json.dumps(
        {
            "jobs": [
                {"title": "No id", "url": "https://apply.workable.com/j/AAA"},
                {"shortcode": "BBB", "url": "https://apply.workable.com/j/BBB"},
                {"shortcode": "CCC", "title": "No url"},
                {
                    "shortcode": "DDD",
                    "title": "Good",
                    "url": "https://apply.workable.com/j/DDD",
                },
            ]
        }
    )
    jobs = WorkableScraper("Test Co", "test").parse(payload)
    assert [j.job_id for j in jobs] == ["DDD"]


def test_an_empty_board_parses_to_no_jobs():
    assert WorkableScraper("Test Co", "test").parse(json.dumps({"jobs": []})) == []


def test_every_board_becomes_a_static_scraper():
    built = scrapers()
    assert len(built) == len(BOARDS)
    assert all(s.config.fetch_mode is FetchMode.STATIC for s in built)
    assert {s.config.name for s in built} == set(BOARDS)
