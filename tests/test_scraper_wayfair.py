import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.wayfair import WayfairScraper

FIXTURE = Path(__file__).parent / "fixtures" / "wayfair_jobs.json"


def record(**overrides):
    base = {
        "id": 60428,
        "eid": "9812",
        "requisitionId": "9812",
        "title": "Retail Sales Associate",
        "applyLink": "https://wayfair.avature.net/en_US/careers?folderId=9812",
        "createdDate": "2025-10-16T12:16:20.350000",
        "isActive": True,
        "isHidden": False,
        "isReferralOnly": False,
        "location": {"name": "Wilmette, IL", "city": "Wilmette", "state": "Illinois",
                     "country": "United States"},
    }
    base.update(overrides)
    return base


def payload(*records):
    return json.dumps({"jobListData": list(records)})


@pytest.fixture(scope="module")
def wayfair_jobs():
    return WayfairScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(wayfair_jobs):
    assert len(wayfair_jobs) == 40
    assert len({j.job_id for j in wayfair_jobs}) == 40


def test_job_id_is_the_requisition_id_that_appears_in_the_url(wayfair_jobs):
    # The internal row id is not in the posting URL; the requisition id is, as
    # ?folderId=, which keeps a snapshot entry traceable to its listing.
    for job in wayfair_jobs:
        assert f"folderId={job.job_id}" in job.url


def test_posted_date_comes_from_created_date(wayfair_jobs):
    assert all(j.posted_date for j in wayfair_jobs)
    assert all(len(j.posted_date) == 10 for j in wayfair_jobs)


def test_posted_dates_are_spread_out_rather_than_a_crawl_timestamp(wayfair_jobs):
    # Unlike the index timestamps Dynatrace and Joby expose, this one is real:
    # the fixture's dates differ from each other rather than clustering.
    assert len({j.posted_date for j in wayfair_jobs}) > 5


def test_location_uses_the_display_name():
    (job,) = WayfairScraper().parse(payload(record()))
    assert job.location == "Wilmette, IL"


def test_location_is_assembled_when_the_display_name_is_missing():
    (job,) = WayfairScraper().parse(
        payload(record(location={"city": "Berlin", "country": "Germany"}))
    )
    assert job.location == "Berlin, Germany"


def test_a_posting_with_no_location_object_has_no_location():
    (job,) = WayfairScraper().parse(payload(record(location=None)))
    assert job.location is None


def test_hidden_and_referral_only_postings_are_not_reported():
    jobs = WayfairScraper().parse(
        payload(
            record(requisitionId="1", isHidden=True),
            record(requisitionId="2", isReferralOnly=True),
            record(requisitionId="3", isActive=False),
            record(requisitionId="4"),
        )
    )
    assert [j.job_id for j in jobs] == ["4"]


def test_a_record_missing_a_title_or_link_is_skipped():
    jobs = WayfairScraper().parse(
        payload(record(requisitionId="1", title=None),
                record(requisitionId="2", applyLink=None, structuredDataApplyLink=None),
                record(requisitionId="3"))
    )
    assert [j.job_id for j in jobs] == ["3"]


def test_the_structured_link_is_used_when_the_apply_link_is_absent():
    (job,) = WayfairScraper().parse(
        payload(record(applyLink=None,
                       structuredDataApplyLink="https://wayfair.avature.net/en_US/careers?folderId=9812"))
    )
    assert job.url.endswith("folderId=9812")


def test_an_empty_board_parses_to_no_jobs():
    assert WayfairScraper().parse(json.dumps({"jobListData": []})) == []


def test_config_asks_for_json_or_the_endpoint_serves_the_page_html():
    config = WayfairScraper().config
    assert config.name == "Wayfair"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.request_headers == {"Accept": "application/json"}
