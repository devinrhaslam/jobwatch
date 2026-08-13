import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.jibe import BOARDS, PAGE_SIZE, JibeScraper


def AMDScraper():
    """AMD, now one entry in the parameterised iCIMS career-site scraper."""
    host, posting_url, extra = BOARDS["AMD"]
    return JibeScraper("AMD", host, posting_url, extra)

FIXTURE = Path(__file__).parent / "fixtures" / "amd_jobs.json"


def record(**overrides):
    base = {
        "slug": "90120", "req_id": "90120", "title": "SOC Design Engineer",
        "city": "Markham", "state": "Ontario", "country": "Canada",
        "location_name": "CA,ON,Markham-1CV",
        "posted_date": "2026-08-11T16:17:00+0000",
        "update_date": "2026-08-11T16:26:51+0000",
    }
    base.update(overrides)
    return base


def payload(*records):
    return json.dumps({"jobs": [{"data": r} for r in records], "totalCount": len(records)})


@pytest.fixture(scope="module")
def amd_jobs():
    return AMDScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(amd_jobs):
    assert len(amd_jobs) == 40
    assert len({j.job_id for j in amd_jobs}) == 40


def test_url_is_the_public_careers_page_not_the_icims_apply_host(amd_jobs):
    # apply_url points at careers-amd.icims.com, which answers 403 "Your IP
    # address is not on a trusted network" — useless as a reported link.
    for job in amd_jobs:
        assert job.url == f"https://careers.amd.com/careers-home/jobs/{job.job_id}"


def test_location_comes_from_the_parts_not_the_site_code():
    (job,) = AMDScraper().parse(payload(record()))
    assert job.location == "Markham, Ontario, Canada"


def test_a_repeated_part_is_listed_once():
    (job,) = AMDScraper().parse(payload(record(city="Singapore", state="Singapore", country="Singapore")))
    assert job.location == "Singapore"


def test_posted_date_is_taken_from_posted_date(amd_jobs):
    assert all(j.posted_date for j in amd_jobs)
    assert all(len(j.posted_date) == 10 for j in amd_jobs)


def test_req_id_is_the_fallback_when_slug_is_absent():
    (job,) = AMDScraper().parse(payload(record(slug=None)))
    assert job.job_id == "90120"


def test_records_missing_an_id_or_title_are_skipped():
    jobs = AMDScraper().parse(
        payload(record(slug=None, req_id=None), record(slug="2", title=None), record(slug="3"))
    )
    assert [j.job_id for j in jobs] == ["3"]


def test_an_entry_without_a_data_object_is_skipped():
    raw = json.dumps({"jobs": [{"nodata": True}, {"data": record(slug="7")}]})
    assert [j.job_id for j in AMDScraper().parse(raw)] == ["7"]


def test_a_full_page_asks_for_the_next_one():
    full = payload(*[record(slug=str(i)) for i in range(PAGE_SIZE)])
    nxt = AMDScraper().next_page_url(full, AMDScraper().config.career_url)
    assert parse_qs(urlsplit(nxt).query)["page"] == ["2"]


def test_a_short_page_ends_pagination():
    short = payload(*[record(slug=str(i)) for i in range(PAGE_SIZE - 1)])
    assert AMDScraper().next_page_url(short, AMDScraper().config.career_url) is None


def test_config_asks_for_the_hundred_page_size_and_honours_the_crawl_delay():
    config = AMDScraper().config
    assert config.name == "AMD"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.inter_page_delay_seconds == 5.0
    params = parse_qs(urlsplit(config.career_url).query)
    assert params["limit"] == [str(PAGE_SIZE)]
    assert params["internal"] == ["false"]
