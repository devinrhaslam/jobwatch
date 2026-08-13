import json
from pathlib import Path

import pytest

from jobwatch.fetch import split_post_url
from jobwatch.models import FetchMode
from jobwatch.scrapers.walmart import PAGE_SIZE, QUERY, WalmartScraper

# A real full read of the board. The per-job `text` (the whole job description)
# and a few unused metadata blocks are replaced with placeholders, taking the
# fixture from 7.9 MB to 1.2 MB; every field the scraper reads is untouched.
FIXTURE = Path(__file__).parent / "fixtures" / "walmart_tech_search.json"


@pytest.fixture(scope="module")
def jobs():
    return WalmartScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_the_whole_technology_board(jobs):
    assert len(jobs) == 684
    assert len({j.job_id for j in jobs}) == 684


def test_job_id_drops_the_external_suffix(jobs):
    # Ids arrive as "R-2484821-External" but the posting page is /jobs/R-2484821;
    # keeping the suffix would produce a board of dead links.
    assert all(j.job_id.startswith("R-") for j in jobs)
    assert not any(j.job_id.endswith("-External") for j in jobs)
    assert all(j.url == f"https://careers.walmart.com/us/en/jobs/{j.job_id}" for j in jobs)


def test_every_posting_has_a_title_location_and_date(jobs):
    assert all(j.title for j in jobs)
    assert all(j.location for j in jobs)
    assert all(j.posted_date and len(j.posted_date) == 10 for j in jobs)


def test_shouted_city_names_are_normalised(jobs):
    # The API returns "BENTONVILLE"; a report full of capitals reads as broken.
    assert not any(j.location.split(",")[0].isupper() for j in jobs)
    assert any(j.location.startswith("Bentonville, AR") for j in jobs)


def test_state_and_country_codes_keep_their_capitals(jobs):
    assert any(j.location.endswith(", CA, US") for j in jobs)


def test_a_short_read_is_an_error_not_a_smaller_board():
    # The search is relevance-scored and its ordering shifts between calls, so a
    # truncated read is a different subset each run. Reporting the difference
    # between two arbitrary subsets as new jobs is the failure this prevents.
    payload = json.dumps({"totalJobs": 684, "jobs": [_record()]})
    with pytest.raises(ValueError, match="1 of 684"):
        WalmartScraper().parse(payload)


def test_a_full_read_is_accepted():
    payload = json.dumps({"totalJobs": 1, "jobs": [_record()]})
    assert len(WalmartScraper().parse(payload)) == 1


def test_a_response_without_a_total_is_not_rejected():
    payload = json.dumps({"jobs": [_record()]})
    assert len(WalmartScraper().parse(payload)) == 1


def test_records_without_id_or_title_are_skipped():
    payload = json.dumps(
        {
            "totalJobs": 3,
            "jobs": [
                {"id": "R-1-External", "metadata": {}},
                {"metadata": {"title": "No id"}},
                _record(),
            ],
        }
    )
    assert [j.job_id for j in WalmartScraper().parse(payload)] == ["R-9"]


def test_posted_date_comes_from_the_posting_start_date():
    payload = json.dumps(
        {"totalJobs": 1, "jobs": [_record(jobPostingStartDate=1782864000000)]}
    )
    assert WalmartScraper().parse(payload)[0].posted_date == "2026-07-01"


def test_missing_start_date_leaves_posted_date_unset():
    payload = json.dumps({"totalJobs": 1, "jobs": [_record(jobPostingStartDate=None)]})
    assert WalmartScraper().parse(payload)[0].posted_date is None


def test_partial_location_is_tolerated():
    payload = json.dumps(
        {
            "totalJobs": 1,
            "jobs": [
                _record(primaryLocationState=None, primaryLocationCountry=None)
            ],
        }
    )
    assert WalmartScraper().parse(payload)[0].location == "Sunnyvale"


def test_config_asks_for_the_technology_area_in_one_whole_read():
    config = WalmartScraper().config
    assert config.name == "Walmart Global Tech"
    assert config.fetch_mode is FetchMode.JSON_POST
    endpoint, body = split_post_url(config.career_url)
    assert f"size={PAGE_SIZE}" in endpoint
    # The narrowing lives in the query string, not the `filter` field — that is
    # what keeps this to 684 technology roles instead of 15,473 company-wide.
    assert body["query"] == QUERY == "areas IN [Technology]"
    assert body["filter"] == ""


def test_every_parsed_posting_is_in_the_technology_area(jobs):
    # The guard against the query silently widening: if the filter syntax ever
    # stops being honoured, the board becomes company-wide retail overnight.
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))["jobs"]
    assert all("Technology" in (r["metadata"].get("areas") or []) for r in records)
    assert len(records) == len(jobs)


def _record(**metadata):
    md = {
        "title": "Staff, Software Engineer",
        "primaryLocationCity": "SUNNYVALE",
        "primaryLocationState": "CA",
        "primaryLocationCountry": "US",
        "jobPostingStartDate": 1782864000000,
    }
    md.update(metadata)
    return {"id": "R-9-External", "metadata": md}
