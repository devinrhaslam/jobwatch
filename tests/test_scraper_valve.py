from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.valve import ValveScraper

FIXTURE = Path(__file__).parent / "fixtures" / "valve_jobs.html"


@pytest.fixture(scope="module")
def valve_jobs():
    return ValveScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_the_postings_in_the_fixture(valve_jobs):
    assert len(valve_jobs) == 27
    assert len({j.job_id for j in valve_jobs}) == 27


def test_a_posting_linked_from_several_sections_is_reported_once():
    # The page lists each role under more than one heading.
    payload = ('<a href="/en/jobs?job_id=85">Audio Software Engineer</a>'
               '<a href="/en/jobs?job_id=85">Audio Software Engineer</a>')
    assert len(ValveScraper().parse(payload)) == 1


def test_job_id_comes_from_the_query_parameter(valve_jobs):
    for job in valve_jobs:
        assert job.job_id.isdigit()
        assert job.url == f"https://www.valvesoftware.com/en/jobs?job_id={job.job_id}"


def test_title_comes_from_the_anchor_text():
    payload = '<a href="/en/jobs?job_id=85">Audio Software Engineer</a>'
    (job,) = ValveScraper().parse(payload)
    assert job.title == "Audio Software Engineer"


def test_links_without_a_job_id_are_ignored():
    payload = ('<a href="/en/about">About</a>'
               '<a href="/en/jobs?job_id=2">3D Character Artist</a>')
    assert [j.job_id for j in ValveScraper().parse(payload)] == ["2"]


def test_a_link_with_no_text_is_skipped():
    payload = ('<a href="/en/jobs?job_id=99"></a>'
               '<a href="/en/jobs?job_id=2">3D Character Artist</a>')
    assert [j.job_id for j in ValveScraper().parse(payload)] == ["2"]


def test_the_board_includes_engineering_roles(valve_jobs):
    # Sanity that this is the real board rather than a category page: Valve's
    # listing is broad areas, and software roles are among them.
    titles = " ".join(j.title.lower() for j in valve_jobs)
    assert "engineer" in titles


def test_no_location_or_posted_date_is_claimed(valve_jobs):
    assert all(j.location is None for j in valve_jobs)
    assert all(j.posted_date is None for j in valve_jobs)


def test_a_page_with_no_openings_parses_to_no_jobs():
    assert ValveScraper().parse("<html><body>nothing here</body></html>") == []


def test_config_reads_the_front_page_over_plain_http():
    config = ValveScraper().config
    assert config.name == "Valve"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.career_url == "https://www.valvesoftware.com/en/"


def test_a_title_split_across_elements_keeps_a_separator():
    # Valve renders some titles as two elements; joining with nothing gives
    # "Software EngineeringOther".
    payload = '<a href="/en/jobs?job_id=57"><span>Software Engineering</span><span>Other</span></a>'
    (job,) = ValveScraper().parse(payload)
    assert job.title == "Software Engineering Other"
