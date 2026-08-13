import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.comeet import BOARDS, ComeetScraper, scrapers

FIXTURE = Path(__file__).parent / "fixtures" / "comeet_vastdata_positions.json"

UID, TOKEN = BOARDS["VAST Data"]


def scraper() -> ComeetScraper:
    return ComeetScraper("VAST Data", UID, TOKEN)


def record(**overrides):
    base = {
        "uid": "6D.76F",
        "name": "Account Executive - Austin, TX",
        "url_active_page": "https://www.comeet.com/jobs/vastdata/43.001/account-executive/6D.76F",
        "location": {"name": "Austin, TX", "city": "Austin", "country": "US"},
        "is_internal": False,
        "time_updated": "2026-05-28T16:27:09Z",
    }
    base.update(overrides)
    return base


@pytest.fixture(scope="module")
def vast_jobs():
    return scraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(vast_jobs):
    assert len(vast_jobs) == 40
    assert len({j.job_id for j in vast_jobs}) == 40


def test_job_id_is_the_uid_and_appears_in_the_url(vast_jobs):
    for job in vast_jobs:
        assert job.url.endswith(job.job_id)


def test_internal_postings_are_not_reported():
    jobs = scraper().parse(json.dumps([record(uid="1", is_internal=True), record(uid="2")]))
    assert [j.job_id for j in jobs] == ["2"]


def test_location_uses_the_display_name():
    (job,) = scraper().parse(json.dumps([record()]))
    assert job.location == "Austin, TX"


def test_location_is_assembled_when_the_name_is_missing():
    (job,) = scraper().parse(
        json.dumps([record(location={"city": "Tel Aviv", "country": "IL"})])
    )
    assert job.location == "Tel Aviv, IL"


def test_a_posting_without_a_location_has_none():
    (job,) = scraper().parse(json.dumps([record(location=None)]))
    assert job.location is None


def test_the_hosted_page_is_used_when_the_active_page_is_absent():
    (job,) = scraper().parse(
        json.dumps([record(url_active_page=None,
                           url_comeet_hosted_page="https://www.comeet.com/jobs/x/1/y/6D.76F")])
    )
    assert job.url.endswith("6D.76F")


def test_records_missing_an_id_title_or_url_are_skipped():
    jobs = scraper().parse(
        json.dumps([record(uid=None), record(uid="2", name=None),
                    record(uid="3", url_active_page=None, url_comeet_hosted_page=None),
                    record(uid="4")])
    )
    assert [j.job_id for j in jobs] == ["4"]


def test_no_posted_date_is_claimed(vast_jobs):
    # time_updated is a modification time, the same reason the Greenhouse
    # scraper refuses updated_at.
    assert all(j.posted_date is None for j in vast_jobs)


def test_an_empty_board_parses_to_no_jobs():
    assert scraper().parse("[]") == []


def test_a_non_list_payload_parses_to_no_jobs():
    assert scraper().parse(json.dumps({"error": "bad token"})) == []


def test_every_board_becomes_a_static_scraper():
    built = scrapers()
    assert len(built) == len(BOARDS)
    assert all(s.config.fetch_mode is FetchMode.STATIC for s in built)
    assert all("careers-api" in s.config.career_url for s in built)
    assert {s.config.name for s in built} == set(BOARDS)
