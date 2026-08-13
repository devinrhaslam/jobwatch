import json
from pathlib import Path

import pytest

from jobwatch.fetch import split_post_url
from jobwatch.models import FetchMode
from jobwatch.scrapers.ashby import (
    GRAPHQL_BOARDS,
    GRAPHQL_URL,
    AshbyGraphQLScraper,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ashby_graphql_whatnot_jobs.json"


@pytest.fixture(scope="module")
def whatnot_jobs():
    scraper = AshbyGraphQLScraper("Whatnot", "whatnot")
    return scraper.parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(whatnot_jobs):
    assert len(whatnot_jobs) == 139
    assert len({j.job_id for j in whatnot_jobs}) == 139


def test_job_ids_are_the_board_uuids(whatnot_jobs):
    job = whatnot_jobs[0]
    assert len(job.job_id) == 36 and job.job_id.count("-") == 4
    assert job.job_id in job.url


def test_url_points_at_the_hosted_board(whatnot_jobs):
    # This endpoint returns no URL of its own, so the posting link is built
    # from the slug and id; getting that wrong would produce a board of dead
    # links that still parse cleanly.
    assert all(j.url.startswith("https://jobs.ashbyhq.com/whatnot/") for j in whatnot_jobs)


def test_posted_date_is_unset_because_the_endpoint_omits_it(whatnot_jobs):
    assert all(j.posted_date is None for j in whatnot_jobs)


def test_secondary_locations_are_appended_to_the_primary():
    payload = json.dumps(
        {
            "data": {
                "jobBoard": {
                    "jobPostings": [
                        {
                            "id": "abc",
                            "title": "Software Engineer",
                            "locationName": "San Francisco, CA",
                            "secondaryLocations": [
                                {"locationName": "New York, NY"},
                                {"locationName": "Los Angeles, CA"},
                            ],
                        }
                    ]
                }
            }
        }
    )
    job = AshbyGraphQLScraper("Acme", "acme").parse(payload)[0]
    assert job.location == "San Francisco, CA, New York, NY, Los Angeles, CA"


def test_duplicate_secondary_location_is_not_repeated():
    payload = json.dumps(
        {
            "data": {
                "jobBoard": {
                    "jobPostings": [
                        {
                            "id": "abc",
                            "title": "Engineer",
                            "locationName": "Remote",
                            "secondaryLocations": [{"locationName": "Remote"}],
                        }
                    ]
                }
            }
        }
    )
    assert AshbyGraphQLScraper("Acme", "acme").parse(payload)[0].location == "Remote"


def test_records_without_id_or_title_are_skipped():
    payload = json.dumps(
        {
            "data": {
                "jobBoard": {
                    "jobPostings": [
                        {"title": "No id"},
                        {"id": "a"},
                        {"id": "c", "title": "Good"},
                    ]
                }
            }
        }
    )
    jobs = AshbyGraphQLScraper("Acme", "acme").parse(payload)
    assert [j.job_id for j in jobs] == ["c"]


def test_error_response_yields_no_jobs():
    # A GraphQL validation error comes back 200 with `data` null; that must
    # read as an empty board rather than raising.
    payload = json.dumps({"errors": [{"message": "boom"}], "data": None})
    assert AshbyGraphQLScraper("Acme", "acme").parse(payload) == []


def test_unknown_board_yields_no_jobs():
    payload = json.dumps({"data": {"jobBoard": None}})
    assert AshbyGraphQLScraper("Acme", "acme").parse(payload) == []


def test_config_carries_the_board_name_in_the_post_body():
    scraper = AshbyGraphQLScraper("Whatnot", "whatnot")
    assert scraper.config.fetch_mode is FetchMode.JSON_POST
    endpoint, body = split_post_url(scraper.config.career_url)
    assert endpoint == GRAPHQL_URL
    assert body["variables"]["organizationHostedJobsPageName"] == "whatnot"
    assert "jobBoardWithTeams" in body["query"]


def test_graphql_boards_do_not_overlap_the_posting_api_boards():
    from jobwatch.scrapers.ashby import BOARDS

    assert not set(BOARDS) & set(GRAPHQL_BOARDS)
