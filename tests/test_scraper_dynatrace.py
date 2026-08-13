import json
from pathlib import Path

import pytest

from jobwatch.fetch import split_post_url
from jobwatch.models import FetchMode
from jobwatch.scrapers.dynatrace import PAGE_SIZE, DynatraceScraper

FIXTURE = Path(__file__).parent / "fixtures" / "dynatrace_jobs.json"


def result(job_id="1353078300", title="Engineer", **raw):
    return {
        "title": title,
        "clickUri": f"https://www.dynatrace.com/careers/jobs/{job_id}/",
        "uri": f"https://www.dynatrace.com/careers/jobs/{job_id}/",
        "raw": raw,
    }


def payload(*results):
    return json.dumps({"totalCount": len(results), "results": list(results)})


@pytest.fixture(scope="module")
def dynatrace_jobs():
    return DynatraceScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_a_full_page_of_the_fixture(dynatrace_jobs):
    assert len(dynatrace_jobs) == PAGE_SIZE
    assert len({j.job_id for j in dynatrace_jobs}) == PAGE_SIZE


def test_job_id_is_the_id_in_the_posting_url(dynatrace_jobs):
    for job in dynatrace_jobs:
        assert job.job_id.isdigit()
        assert f"/careers/jobs/{job.job_id}" in job.url


def test_location_lists_offices_then_countries():
    (job,) = DynatraceScraper().parse(
        payload(result(office_locations=["Tokyo"], country=["Japan"]))
    )
    assert job.location == "Tokyo, Japan"


def test_multiple_offices_are_all_kept():
    (job,) = DynatraceScraper().parse(
        payload(result(office_locations=["Vienna", "Linz"], country=["Austria"]))
    )
    assert job.location == "Vienna, Linz, Austria"


def test_a_repeated_place_is_listed_once():
    (job,) = DynatraceScraper().parse(
        payload(result(office_locations=["Remote"], country=["Remote"]))
    )
    assert job.location == "Remote"


def test_a_string_location_field_is_accepted_like_a_list():
    (job,) = DynatraceScraper().parse(payload(result(office_locations="Boston")))
    assert job.location == "Boston"


def test_a_posting_with_no_place_has_no_location():
    (job,) = DynatraceScraper().parse(payload(result()))
    assert job.location is None


def test_no_posted_date_is_claimed(dynatrace_jobs):
    # Every result carries a `date`, but a whole page of them lands within a few
    # seconds and moves with each crawl: it is when the index saw the posting.
    assert all(j.posted_date is None for j in dynatrace_jobs)


def test_a_result_without_a_job_id_in_its_url_is_skipped():
    bad = {"title": "Engineer", "clickUri": "https://www.dynatrace.com/careers/", "raw": {}}
    jobs = DynatraceScraper().parse(payload(bad, result()))
    assert [j.job_id for j in jobs] == ["1353078300"]


def test_a_result_without_a_title_is_skipped():
    bad = {"clickUri": "https://www.dynatrace.com/careers/jobs/99/", "raw": {}}
    assert DynatraceScraper().parse(payload(bad)) == []


def test_a_full_page_asks_for_the_next_offset():
    full = payload(*[result(job_id=str(i)) for i in range(PAGE_SIZE)])
    nxt = DynatraceScraper().next_page_url(full, DynatraceScraper().config.career_url)
    _, body = split_post_url(nxt)
    assert body["firstResult"] == PAGE_SIZE
    assert body["numberOfResults"] == PAGE_SIZE


def test_a_short_page_ends_pagination():
    short = payload(*[result(job_id=str(i)) for i in range(PAGE_SIZE - 1)])
    assert DynatraceScraper().next_page_url(short, DynatraceScraper().config.career_url) is None


def test_an_empty_response_parses_to_no_jobs():
    assert DynatraceScraper().parse(json.dumps({"results": []})) == []


def test_config_posts_to_the_proxy_on_dynatraces_own_domain():
    config = DynatraceScraper().config
    assert config.name == "Dynatrace"
    assert config.fetch_mode is FetchMode.JSON_POST
    endpoint, body = split_post_url(config.career_url)
    assert endpoint == "https://www.dynatrace.com/api/coveo/search/"
    assert body["firstResult"] == 0
