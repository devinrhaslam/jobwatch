import json

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.tesla import SOFTWARE_DEPARTMENTS, TeslaScraper, _slug

# The board's own numbering as of 2026-08-05. The ids are positional, so these
# are a snapshot of one payload rather than a fixed scheme — see
# test_follows_a_renumbering_instead_of_watching_the_wrong_department.
_DEPARTMENTS = {
    "1": "Vehicle Service",
    "3": "Tesla AI",
    "7": "Vehicle Software",
    "8": "Engineering & Information Technology",
    "9": "Manufacturing",
}


def _state(listings, locations=None, departments=None):
    # Listings default to a watched department so that tests about parsing are
    # not silently testing the department filter instead.
    listings = [
        {**row, "dp": row.get("dp", "8")} if isinstance(row, dict) else row
        for row in listings
    ]
    return json.dumps(
        {
            "lookup": {
                "locations": locations
                if locations is not None
                else {"401022": "Palo Alto, California"},
                "departments": _DEPARTMENTS if departments is None else departments,
                "types": {"1": "fulltime"},
            },
            "listings": listings,
        }
    )


def test_parses_listing_into_job_with_resolved_location():
    payload = _state(
        [{"id": "224501", "t": "AI Engineer, Manipulation, Optimus", "l": "401022"}]
    )

    jobs = TeslaScraper().parse(payload)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "Tesla"
    assert job.job_id == "224501"
    assert job.title == "AI Engineer, Manipulation, Optimus"
    assert job.location == "Palo Alto, California"
    assert job.url == (
        "https://www.tesla.com/careers/search/job/"
        "ai-engineer-manipulation-optimus-224501"
    )


def test_location_is_none_when_the_lookup_has_no_entry():
    # A location id missing from the table must not drop the job: an
    # unlocatable posting is still a posting, and the report-time filter
    # treats a blank location as unknown rather than as a match.
    jobs = TeslaScraper().parse(_state([{"id": "1", "t": "Engineer", "l": "999999"}]))

    assert len(jobs) == 1
    assert jobs[0].location is None


def test_skips_records_missing_an_id_or_title():
    payload = _state(
        [
            {"id": "1", "t": "Engineer", "l": "401022"},
            {"id": "2", "l": "401022"},
            {"t": "No Id", "l": "401022"},
            "not-a-dict",
        ]
    )

    assert [job.job_id for job in TeslaScraper().parse(payload)] == ["1"]


def test_board_arrives_whole_so_there_is_no_next_page():
    assert TeslaScraper().next_page_url(_state([]), "https://example.com") is None


def test_config_captures_the_state_api_in_firefox():
    config = TeslaScraper().config
    assert config.fetch_mode is FetchMode.RENDERED_XHR
    # Headless Chromium is served "Access Denied" by Tesla's bot filter while
    # headless Firefox is served the page, so the engine is load-bearing.
    assert config.browser_engine == "firefox"
    assert config.capture_response_url == "/cua-api/apps/careers/state"


def test_slug_collapses_punctuation_the_way_tesla_does():
    assert _slug("Reinforcement Learning Engineer, Self-Driving") == (
        "reinforcement-learning-engineer-self-driving"
    )
    assert _slug("Sr. Engineer (Powertrain) & Systems") == (
        "sr-engineer-powertrain-systems"
    )


def test_keeps_only_software_departments():
    payload = _state(
        [
            {"id": "eng", "t": "Backend Engineer", "dp": "8"},
            {"id": "ai", "t": "AI Engineer", "dp": "3"},
            {"id": "vehicle", "t": "Distributed Systems Engineer", "dp": "7"},
            {"id": "factory", "t": "Production Associate", "dp": "9"},
            {"id": "service", "t": "Service Technician", "dp": "1"},
        ]
    )

    kept = {job.job_id for job in TeslaScraper().parse(payload)}

    assert kept == {"eng", "ai", "vehicle"}


def test_department_filter_does_not_second_guess_titles():
    # A mechanical engineer sits in the same department as a backend engineer.
    # Dropping it here would mean matching on title text, which is exactly the
    # judgement the report-time LLM filter exists to make.
    payload = _state([{"id": "1", "t": "Thermal Design Engineer", "dp": "8"}])

    assert [job.job_id for job in TeslaScraper().parse(payload)] == ["1"]


def test_follows_a_renumbering_instead_of_watching_the_wrong_department():
    # Tesla's department ids are positional: on 2026-08-05 the list shifted by
    # one, moving "Engineering & Information Technology" onto the id "Vehicle
    # Software" had held and "Manufacturing" onto its old one. Reading the ids
    # out of the payload's own lookup keeps the same three departments watched
    # across a shift that a hard-coded id could only fail on or follow blindly.
    shifted = {
        "1": "Vehicle Service",
        "3": "Tesla AI",
        "8": "Vehicle Software",
        "9": "Engineering & Information Technology",
        "10": "Manufacturing",
    }
    payload = _state(
        [
            {"id": "eng", "t": "Backend Engineer", "dp": "9"},
            {"id": "vehicle", "t": "Distributed Systems Engineer", "dp": "8"},
            {"id": "factory", "t": "Production Associate", "dp": "10"},
        ],
        departments=shifted,
    )

    kept = {job.job_id for job in TeslaScraper().parse(payload)}

    assert kept == {"eng", "vehicle"}


def test_raises_when_a_watched_department_leaves_the_board():
    # A rename or retirement drops a third of the watched board, which on its
    # own is indistinguishable from a quiet week. Fail the company instead.
    payload = _state(
        [{"id": "1", "t": "Backend Engineer", "dp": "8"}],
        departments={**_DEPARTMENTS, "7": "Vehicle Firmware"},
    )

    with pytest.raises(ValueError, match="Vehicle Software"):
        TeslaScraper().parse(payload)


def test_accepts_a_payload_whose_department_names_are_unchanged():
    payload = _state([{"id": "1", "t": "Backend Engineer", "dp": "8"}])

    assert len(TeslaScraper().parse(payload)) == 1


def test_watched_departments_are_the_software_ones():
    assert SOFTWARE_DEPARTMENTS == {
        "Tesla AI",
        "Vehicle Software",
        "Engineering & Information Technology",
    }
