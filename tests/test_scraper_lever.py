import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.lever import BOARDS, LeverScraper, scrapers

FIXTURE = Path(__file__).parent / "fixtures" / "lever_spotify_jobs.json"


@pytest.fixture(scope="module")
def spotify_jobs():
    return LeverScraper("Spotify", "spotify").parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(spotify_jobs):
    assert len(spotify_jobs) == 102
    assert len({j.job_id for j in spotify_jobs}) == 102


def test_job_ids_are_the_board_uuids(spotify_jobs):
    # Lever keys on a UUID, and it appears in the posting URL, so a snapshot
    # entry stays traceable back to the listing it came from.
    job = spotify_jobs[0]
    assert len(job.job_id) == 36 and job.job_id.count("-") == 4
    assert job.job_id in job.url


def test_title_comes_from_the_text_field(spotify_jobs):
    # Lever names the title "text", not "title" — reading the wrong key would
    # silently produce a board of empty titles rather than an error.
    assert all(j.title for j in spotify_jobs)


def test_posted_date_is_populated_from_created_at(spotify_jobs):
    assert all(j.posted_date for j in spotify_jobs)
    assert all(len(j.posted_date) == 10 for j in spotify_jobs)  # YYYY-MM-DD


def test_url_is_the_posting_page_not_the_apply_form(spotify_jobs):
    assert all(j.url.startswith("https://jobs.lever.co/spotify/") for j in spotify_jobs)
    assert not any(j.url.endswith("/apply") for j in spotify_jobs)


def test_all_locations_are_appended_to_the_primary():
    payload = json.dumps(
        [
            {
                "id": "abc",
                "text": "Software Engineer",
                "hostedUrl": "https://jobs.lever.co/acme/abc",
                "categories": {
                    "location": "Stockholm",
                    "allLocations": ["Stockholm", "London", "New York"],
                },
            }
        ]
    )
    job = LeverScraper("Acme", "acme").parse(payload)[0]
    assert job.location == "Stockholm, London, New York"


def test_primary_location_is_not_repeated_from_all_locations():
    payload = json.dumps(
        [
            {
                "id": "abc",
                "text": "Software Engineer",
                "hostedUrl": "https://jobs.lever.co/acme/abc",
                "categories": {"location": "Stockholm", "allLocations": ["Stockholm"]},
            }
        ]
    )
    job = LeverScraper("Acme", "acme").parse(payload)[0]
    assert job.location == "Stockholm"


def test_multi_location_postings_are_present_in_the_real_board(spotify_jobs):
    # 32 of Spotify's postings list more than one site; if allLocations stopped
    # being read, every location would collapse to a single city and this would
    # catch it.
    assert sum(1 for j in spotify_jobs if j.location and ", " in j.location) >= 30


def test_apply_url_is_used_when_hosted_url_is_missing():
    payload = json.dumps(
        [
            {
                "id": "abc",
                "text": "Software Engineer",
                "applyUrl": "https://jobs.lever.co/acme/abc/apply",
            }
        ]
    )
    job = LeverScraper("Acme", "acme").parse(payload)[0]
    assert job.url == "https://jobs.lever.co/acme/abc/apply"


def test_records_without_id_title_or_url_are_skipped():
    payload = json.dumps(
        [
            {"text": "No id", "hostedUrl": "https://jobs.lever.co/acme/x"},
            {"id": "a", "hostedUrl": "https://jobs.lever.co/acme/a"},
            {"id": "b", "text": "No url"},
            {"id": "c", "text": "Good", "hostedUrl": "https://jobs.lever.co/acme/c"},
        ]
    )
    jobs = LeverScraper("Acme", "acme").parse(payload)
    assert [j.job_id for j in jobs] == ["c"]


def test_missing_created_at_leaves_posted_date_unset():
    payload = json.dumps(
        [{"id": "a", "text": "T", "hostedUrl": "https://jobs.lever.co/acme/a"}]
    )
    assert LeverScraper("Acme", "acme").parse(payload)[0].posted_date is None


def test_non_list_payload_yields_no_jobs():
    # The endpoint answers with an object rather than an array for an unknown
    # slug; that must read as an empty board, not raise.
    assert LeverScraper("Acme", "acme").parse(json.dumps({"error": "not found"})) == []


def test_scrapers_cover_every_configured_board():
    built = {s.config.name for s in scrapers()}
    assert built == set(BOARDS)


def test_every_board_is_configured_for_static_fetch():
    for scraper in scrapers():
        assert scraper.config.fetch_mode is FetchMode.STATIC
        assert scraper.config.career_url.startswith("https://api.lever.co/v0/postings/")
        assert scraper.config.career_url.endswith("?mode=json")
