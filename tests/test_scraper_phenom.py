import json
from pathlib import Path

import pytest

from jobwatch.fetch import build_post_url, split_post_url
from jobwatch.models import FetchMode
from jobwatch.scrapers.phenom import BOARDS, PAGE_SIZE, PhenomScraper, scrapers

FIXTURE = Path(__file__).parent / "fixtures" / "phenom_circle_jobs.json"


def scraper() -> PhenomScraper:
    return PhenomScraper("Circle", "careers.circle.com")


def record(**overrides):
    base = {
        "jobId": "JR100477",
        "reqId": "JR100477",
        "jobSeqNo": "CIICIRUSJR100477EXTERNALENUS",
        "title": "Lead Product Manager, Token",
        "location": "San Francisco, California, United States of America",
        "multi_location": ["San Francisco, California, United States of America"],
        "postedDate": "2026-04-06T00:00:00.000+0000",
    }
    base.update(overrides)
    return base


def payload(*records, total=None):
    jobs = list(records)
    return json.dumps(
        {
            "refineSearch": {
                "totalHits": len(jobs) if total is None else total,
                "data": {"jobs": jobs},
            }
        }
    )


@pytest.fixture(scope="module")
def circle_jobs():
    return scraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(circle_jobs):
    assert len(circle_jobs) == 74
    assert len({j.job_id for j in circle_jobs}) == 74


def test_url_is_the_careers_sites_own_posting_page(circle_jobs):
    # Not the applyUrl the record also carries: that points at the retired
    # Workday tenant, which now redirects to Workday's maintenance page.
    assert all(j.url.startswith("https://careers.circle.com/us/en/job/") for j in circle_jobs)
    assert not any("myworkdayjobs" in j.url for j in circle_jobs)


def test_the_built_url_matches_the_sitemaps_canonical_form():
    # Checked live against all 74 job URLs in the sitemap robots.txt publishes;
    # this pins the slug rule that made them identical. Every run of
    # non-alphanumerics collapses to one hyphen.
    (job,) = scraper().parse(payload(record(title="Senior Analyst, AML/Know Your Customer")))
    assert job.url == (
        "https://careers.circle.com/us/en/job/CIICIRUSJR100477EXTERNALENUS/"
        "Senior-Analyst-AML-Know-Your-Customer"
    )


def test_a_multi_location_posting_says_how_many_others_there_are():
    # isMultiLocation is False on postings carrying 25 locations, so the list
    # length is what is counted rather than the flag.
    (job,) = scraper().parse(
        payload(
            record(
                location="San Francisco, California, United States of America",
                multi_location=["San Francisco, California, United States of America"] * 25,
                isMultiLocation=False,
            )
        )
    )
    assert job.location == "San Francisco, California, United States of America (+24 locations)"


def test_a_single_location_posting_is_left_unadorned():
    (job,) = scraper().parse(payload(record(location="Bangalore, India", multi_location=["Bangalore, India"])))
    assert job.location == "Bangalore, India"


def test_a_posting_with_no_location_has_none():
    (job,) = scraper().parse(payload(record(location="", multi_location=[])))
    assert job.location is None


def test_posted_date_is_the_date_part_of_the_timestamp():
    (job,) = scraper().parse(payload(record(postedDate="2026-08-11T00:00:00.000+0000")))
    assert job.posted_date == "2026-08-11"


def test_posted_date_is_a_real_publication_date_not_the_fetch(circle_jobs):
    # The test that separates a real date field from a crawl timestamp: a
    # fabricated one clusters at the moment of the fetch. These take 43 distinct
    # values across 74 postings and span four months.
    dates = [j.posted_date for j in circle_jobs]
    assert all(dates)
    assert len(set(dates)) > 40
    assert min(dates) < "2026-05-01" < max(dates)


def test_a_record_with_an_unusable_date_keeps_no_date():
    (job,) = scraper().parse(payload(record(postedDate=None)))
    assert job.posted_date is None


def test_req_id_stands_in_when_job_id_is_absent():
    (job,) = scraper().parse(payload(record(jobId=None, reqId="JR999")))
    assert job.job_id == "JR999"


def test_records_missing_an_id_title_or_sequence_number_are_skipped():
    jobs = scraper().parse(
        payload(
            record(jobId=None, reqId=None),
            record(jobId="2", title=None),
            record(jobId="3", jobSeqNo=None),
            record(jobId="4"),
        )
    )
    assert [j.job_id for j in jobs] == ["4"]


def test_a_title_with_no_alphanumerics_is_skipped_rather_than_linked_to_nothing():
    assert scraper().parse(payload(record(title="///"))) == []


def test_an_empty_board_parses_to_no_jobs():
    assert scraper().parse(payload()) == []


def test_pagination_stops_once_the_reported_total_is_reached():
    page = payload(*[record(jobId=f"JR{i}") for i in range(PAGE_SIZE)], total=PAGE_SIZE)
    assert scraper().next_page_url(page, scraper().config.career_url) is None


def test_pagination_asks_for_the_next_offset_while_the_total_is_short():
    page = payload(*[record(jobId=f"JR{i}") for i in range(PAGE_SIZE)], total=PAGE_SIZE * 3)
    url = scraper().next_page_url(page, scraper().config.career_url)
    _, body = split_post_url(url)
    assert body["from"] == PAGE_SIZE


def test_a_page_shorter_than_asked_for_is_not_read_as_the_end_of_the_board():
    # A short page is the usual exhaustion signal, but it is also what a
    # server-side cap below the requested size looks like — and reading that as
    # "board finished" is how a seed truncates quietly.
    page = payload(*[record(jobId=f"JR{i}") for i in range(10)], total=500)
    url = scraper().next_page_url(page, scraper().config.career_url)
    _, body = split_post_url(url)
    assert body["from"] == 10


def test_an_empty_page_ends_pagination_even_with_a_total_still_outstanding():
    assert scraper().next_page_url(payload(total=500), scraper().config.career_url) is None


def test_a_missing_total_falls_back_to_paginating_until_a_page_is_empty():
    page = payload(*[record(jobId=f"JR{i}") for i in range(10)], total=None)
    page = json.dumps({"refineSearch": {"data": {"jobs": json.loads(page)["refineSearch"]["data"]["jobs"]}}})
    assert scraper().next_page_url(page, scraper().config.career_url) is not None


def test_the_request_body_carries_only_the_fields_the_endpoint_needs():
    # ddoKey, jobs and size are each load-bearing: dropping any one returns an
    # empty result set with a 200. Everything else was verified inert.
    _, body = split_post_url(scraper().config.career_url)
    assert body == {"ddoKey": "refineSearch", "from": 0, "jobs": True, "size": PAGE_SIZE}


def test_every_board_becomes_a_json_post_scraper_that_reads_in_full():
    built = scrapers()
    assert len(built) == len(BOARDS)
    assert all(s.config.fetch_mode is FetchMode.JSON_POST for s in built)
    # The board comes back in the same order whatever sortBy asks for, and that
    # order is not by postedDate, so the engine's newest-first early stop would
    # miss anything posted deeper in the list.
    assert all(s.config.paginate_fully for s in built)
    assert {s.config.name for s in built} == set(BOARDS)


def test_the_endpoint_is_the_companys_own_careers_host():
    endpoint, _ = split_post_url(scraper().config.career_url)
    assert endpoint == "https://careers.circle.com/widgets"
