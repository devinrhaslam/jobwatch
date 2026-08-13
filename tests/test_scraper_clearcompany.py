import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.clearcompany import PAGE_SIZE, BOARDS, ClearCompanyScraper, scrapers

FIXTURE = Path(__file__).parent / "fixtures" / "clearcompany_firefly_page0.json"

UUID, POSTING = BOARDS["Firefly Aerospace"]


def scraper() -> ClearCompanyScraper:
    return ClearCompanyScraper("Firefly Aerospace", UUID, POSTING)


def record(**overrides):
    base = {
        "id": "1e1b2604-3caa-0a31-3df8-872246a56c04",
        "positionTitle": "Principal Software Engineer",
        "location": "Cedar Park TX",
        "locations": [{"city": "Cedar Park", "subdivision": "TX", "country": "US",
                       "isRemote": False}],
        "postedDate": "2026-08-10T00:00:00",
    }
    base.update(overrides)
    return base


def payload(*records, total=None):
    return json.dumps({"results": list(records),
                       "totalCount": len(records) if total is None else total})


@pytest.fixture(scope="module")
def firefly_jobs():
    return scraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(firefly_jobs):
    assert len(firefly_jobs) == 40
    assert len({j.job_id for j in firefly_jobs}) == 40


def test_url_is_the_companys_own_page_not_the_disallowed_portal(firefly_jobs):
    # <company>.clearcompany.com answers Disallow: / and serves an empty shell;
    # the company's own ?jobId= page renders the posting.
    for job in firefly_jobs:
        assert job.url == f"https://fireflyspace.com/careers/?jobId={job.job_id}"


def test_posted_date_comes_from_posted_date(firefly_jobs):
    assert all(j.posted_date for j in firefly_jobs)
    assert all(len(j.posted_date) == 10 for j in firefly_jobs)


def test_posted_dates_span_months_rather_than_one_moment(firefly_jobs):
    dates = {j.posted_date for j in firefly_jobs}
    assert len(dates) > 3
    assert min(dates) != max(dates)


def test_location_is_built_from_the_structured_entries():
    (job,) = scraper().parse(payload(record()))
    assert job.location == "Cedar Park, TX, US"


def test_every_listed_place_is_kept():
    (job,) = scraper().parse(payload(record(locations=[
        {"city": "Cedar Park", "subdivision": "TX", "country": "US"},
        {"city": "Briggs", "subdivision": "TX", "country": "US"},
    ])))
    assert job.location == "Cedar Park, TX, US; Briggs, TX, US"


def test_a_remote_posting_is_marked():
    (job,) = scraper().parse(payload(record(locations=[
        {"city": "Cedar Park", "subdivision": "TX", "country": "US", "isRemote": True}
    ])))
    assert job.location.endswith("(Remote)")


def test_the_flat_location_is_the_fallback():
    (job,) = scraper().parse(payload(record(locations=[])))
    assert job.location == "Cedar Park TX"


def test_records_missing_an_id_or_title_are_skipped():
    jobs = scraper().parse(payload(record(id=None), record(id="2", positionTitle=None),
                                   record(id="3")))
    assert [j.job_id for j in jobs] == ["3"]


def test_pagination_advances_while_the_total_says_more_remain():
    nxt = scraper().next_page_url(payload(*[record(id=str(i)) for i in range(PAGE_SIZE)],
                                          total=PAGE_SIZE * 2),
                                  scraper().config.career_url)
    assert parse_qs(urlsplit(nxt).query)["pageIndex"] == ["1"]


def test_pagination_stops_once_the_total_is_covered():
    full = payload(*[record(id=str(i)) for i in range(PAGE_SIZE)], total=PAGE_SIZE)
    assert scraper().next_page_url(full, scraper().config.career_url) is None


def test_an_empty_page_ends_pagination():
    assert scraper().next_page_url(payload(total=500), scraper().config.career_url) is None


def test_every_board_becomes_a_static_scraper():
    built = scrapers()
    assert len(built) == len(BOARDS)
    assert all(s.config.fetch_mode is FetchMode.STATIC for s in built)
    assert all("careers-api.clearcompany.com" in s.config.career_url for s in built)
    assert {s.config.name for s in built} == set(BOARDS)
