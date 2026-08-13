import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.atlassian import AtlassianScraper

FIXTURE = Path(__file__).parent / "fixtures" / "atlassian_jobs.json"


@pytest.fixture(scope="module")
def jobs():
    return AtlassianScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_distinct_posting_in_the_fixture(jobs):
    # The fixture holds 241 records but only 226 distinct ids; the rest are
    # verbatim repeats that the parser drops.
    assert len(jobs) == 226
    assert len({j.job_id for j in jobs}) == 226


def test_repeated_records_are_reported_once():
    payload = json.dumps(
        [
            {"id": 1, "title": "Engineer", "locations": ["Sydney"]},
            {"id": 1, "title": "Engineer", "locations": ["Sydney"]},
            {"id": 2, "title": "Designer", "locations": ["Austin"]},
        ]
    )
    assert [j.job_id for j in AtlassianScraper().parse(payload)] == ["1", "2"]


def test_url_is_the_site_posting_page_not_the_icims_apply_form(jobs):
    # Records carry an applyUrl that jumps into iCIMS with ?mode=apply, which
    # skips the description. The report should link to the posting instead.
    assert all(
        j.url.startswith("https://www.atlassian.com/company/careers/details/")
        for j in jobs
    )
    assert not any("icims" in j.url or "mode=apply" in j.url for j in jobs)


def test_job_id_appears_in_the_posting_url(jobs):
    assert all(j.url.endswith(f"/{j.job_id}") for j in jobs)


def test_posted_date_is_unset_because_only_an_edit_time_is_available(jobs):
    # portalJobPost.updatedDate is an edit time, not a publication time; see
    # the scraper docstring for why it is deliberately not reported.
    assert all(j.posted_date is None for j in jobs)


def test_multi_site_roles_list_every_location(jobs):
    assert sum(1 for j in jobs if j.location and ", " in j.location) == 194


def test_postings_without_locations_report_no_location(jobs):
    # 26 of the real board's distinct postings carry an empty locations list;
    # those must read as None rather than an empty string.
    assert sum(1 for j in jobs if j.location is None) == 26
    assert not any(j.location == "" for j in jobs)


def test_duplicate_locations_are_not_repeated():
    payload = json.dumps(
        [{"id": 1, "title": "Engineer", "locations": ["Sydney", "Sydney", "Austin"]}]
    )
    assert AtlassianScraper().parse(payload)[0].location == "Sydney, Austin"


def test_records_without_id_or_title_are_skipped():
    payload = json.dumps(
        [
            {"title": "No id"},
            {"id": 2},
            {"id": 3, "title": "Good"},
        ]
    )
    assert [j.job_id for j in AtlassianScraper().parse(payload)] == ["3"]


def test_non_list_payload_yields_no_jobs():
    assert AtlassianScraper().parse(json.dumps({"error": "nope"})) == []


def test_config_targets_the_listings_endpoint_over_plain_http():
    config = AtlassianScraper().config
    assert config.name == "Atlassian"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.career_url == "https://www.atlassian.com/endpoint/careers/listings"
