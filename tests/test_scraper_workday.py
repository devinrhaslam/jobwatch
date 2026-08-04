import json
from datetime import date
from pathlib import Path

import pytest

from jobwatch.fetch import split_post_url
from jobwatch.models import FetchMode
from jobwatch.scrapers.workday import (
    BOARDS,
    MAX_PAGES,
    PAGE_SIZE,
    WorkdayScraper,
    _posted_date,
    scrapers,
)

FIXTURE = Path(__file__).parent / "fixtures" / "workday_crowdstrike_jobs.json"


def _scraper():
    return WorkdayScraper("CrowdStrike", "crowdstrike", "wd5", "crowdstrikecareers")


@pytest.fixture(scope="module")
def crowdstrike_jobs():
    return _scraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_a_full_page(crowdstrike_jobs):
    assert len(crowdstrike_jobs) == PAGE_SIZE
    assert len({j.job_id for j in crowdstrike_jobs}) == PAGE_SIZE


def test_job_id_is_the_requisition_id(crowdstrike_jobs):
    # Requisition ids survive a title edit; the externalPath slug does not.
    assert all(j.job_id.startswith("R") for j in crowdstrike_jobs)


def test_job_url_points_at_the_public_posting(crowdstrike_jobs):
    job = crowdstrike_jobs[0]
    assert job.url.startswith("https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers/job/")
    assert job.job_id in job.url
    assert "/wday/cxs/" not in job.url  # the API path, not a page a human can open


def test_falls_back_to_the_external_path_when_bullet_fields_are_empty():
    payload = json.dumps(
        {
            "jobPostings": [
                {
                    "title": "Software Engineer",
                    "externalPath": "/job/USA---Austin/Software-Engineer_R12345",
                    "bulletFields": [],
                }
            ]
        }
    )
    assert _scraper().parse(payload)[0].job_id == "R12345"


@pytest.mark.parametrize(
    "posted_on, expected",
    [
        ("Posted Today", "2026-08-03"),
        ("Posted Yesterday", "2026-08-02"),
        ("Posted 5 Days Ago", "2026-07-29"),
        ("Posted 1 Day Ago", "2026-08-02"),
    ],
)
def test_relative_posted_dates_are_resolved(posted_on, expected):
    assert _posted_date({"postedOn": posted_on}, today=date(2026, 8, 3)) == expected


@pytest.mark.parametrize("posted_on", ["Posted 30+ Days Ago", "", "Posted recently", None])
def test_unresolvable_posted_dates_are_left_unset(posted_on):
    # "30+" is a floor, not a date. Reporting it as exactly 30 days old would
    # invent precision the board never gave us.
    assert _posted_date({"postedOn": posted_on}, today=date(2026, 8, 3)) is None


def test_next_page_advances_the_offset(crowdstrike_jobs):
    scraper = _scraper()
    payload = FIXTURE.read_text(encoding="utf-8")
    nxt = scraper.next_page_url(payload, scraper.config.career_url)
    _, body = split_post_url(nxt)
    assert body["offset"] == PAGE_SIZE
    _, first_body = split_post_url(scraper.config.career_url)
    assert first_body["offset"] == 0


def test_a_short_page_ends_pagination():
    scraper = _scraper()
    payload = json.dumps({"jobPostings": [{"title": "x", "externalPath": "/job/a_R1"}]})
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps(
        {
            "jobPostings": [
                {"title": "Kept", "externalPath": "/job/a_R1", "bulletFields": ["R1"]},
                {"title": "No path", "bulletFields": ["R2"]},
                {"externalPath": "/job/c_R3", "bulletFields": ["R3"]},
            ]
        }
    )
    assert [j.job_id for j in _scraper().parse(payload)] == ["R1"]


def test_empty_board_parses_to_no_jobs():
    assert _scraper().parse(json.dumps({"jobPostings": []})) == []


def test_config_uses_post_mode_and_a_raised_page_ceiling():
    scraper = _scraper()
    assert scraper.config.fetch_mode is FetchMode.JSON_POST
    # 20 results per page caps a default-ceiling seed at 400 jobs; the largest
    # tenant here has ~2000.
    assert scraper.config.max_pages == MAX_PAGES
    assert MAX_PAGES * PAGE_SIZE >= 2000


def test_every_board_yields_a_distinct_registered_scraper():
    built = scrapers()
    assert len(built) == len(BOARDS)
    assert {s.config.name for s in built} == set(BOARDS)
    assert len({s.config.career_url for s in built}) == len(BOARDS)


def test_location_falls_back_to_the_posting_path_when_it_is_just_a_count():
    # "3 Locations" cannot be filtered on; the path names the primary site.
    payload = json.dumps(
        {
            "jobPostings": [
                {
                    "title": "Software Engineer",
                    "externalPath": "/job/India---Hyderabad/Software-Engineer_JR1",
                    "bulletFields": ["JR1"],
                    "locationsText": "3 Locations",
                }
            ]
        }
    )
    job = _scraper().parse(payload)[0]
    assert job.location == "India, Hyderabad (+3 Locations)"


def test_a_real_location_is_preferred_over_the_path():
    payload = json.dumps(
        {
            "jobPostings": [
                {
                    "title": "Software Engineer",
                    "externalPath": "/job/India---Hyderabad/Software-Engineer_JR1",
                    "bulletFields": ["JR1"],
                    "locationsText": "USA - Sunnyvale, CA",
                }
            ]
        }
    )
    assert _scraper().parse(payload)[0].location == "USA - Sunnyvale, CA"


def test_multi_word_path_locations_are_readable():
    payload = json.dumps(
        {
            "jobPostings": [
                {
                    "title": "Software Engineer",
                    "externalPath": "/job/California---San-Francisco/Software-Engineer_JR1",
                    "bulletFields": ["JR1"],
                    "locationsText": "2 Locations",
                }
            ]
        }
    )
    assert _scraper().parse(payload)[0].location == "California, San Francisco (+2 Locations)"


def test_missing_location_and_path_yields_none():
    payload = json.dumps(
        {"jobPostings": [{"title": "SWE", "externalPath": "/job/x_JR1", "bulletFields": ["JR1"]}]}
    )
    assert _scraper().parse(payload)[0].location is None
