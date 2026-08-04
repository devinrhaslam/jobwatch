import json

from jobwatch.models import FetchMode
from jobwatch.scrapers.tesla import TeslaScraper, _slug


def _state(listings, locations=None):
    return json.dumps(
        {
            "lookup": {
                "locations": locations
                if locations is not None
                else {"401022": "Palo Alto, California"},
                "departments": {"9": "Engineering & Information Technology"},
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
