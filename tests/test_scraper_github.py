import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.github import PAGE_SIZE, GitHubScraper, _posted_date

FIXTURE = Path(__file__).parent / "fixtures" / "github_jobs.json"


@pytest.fixture(scope="module")
def github_jobs():
    return GitHubScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_the_whole_board(github_jobs):
    assert len(github_jobs) == 71
    assert len({j.job_id for j in github_jobs}) == 71


def test_unwraps_the_data_envelope(github_jobs):
    assert all(j.title and j.job_id for j in github_jobs)


def test_job_link_is_the_public_page_not_the_login_wall(github_jobs):
    # apply_url points at careers-githubinc.icims.com/.../login, which requires
    # an account; the careers-home page is publicly readable.
    for job in github_jobs:
        assert job.url.startswith("https://www.github.careers/careers-home/jobs/")
        assert "icims.com" not in job.url


def test_every_posting_carries_a_date(github_jobs):
    assert all(j.posted_date and len(j.posted_date) == 10 for j in github_jobs)


def test_posted_date_handles_a_colonless_utc_offset():
    assert _posted_date({"posted_date": "2026-08-03T14:02:00+0000"}) == "2026-08-03"


def test_posted_date_falls_back_to_create_date():
    assert _posted_date({"create_date": "2026-07-31T09:00:00+00:00"}) == "2026-07-31"


def test_unparseable_posted_date_is_left_unset():
    assert _posted_date({"posted_date": "last Tuesday"}) is None
    assert _posted_date({}) is None


def test_location_falls_back_to_city_state_country():
    payload = json.dumps(
        {"jobs": [{"data": {"slug": "1", "title": "SWE", "city": "Austin",
                            "state": "TX", "country": "United States"}}]}
    )
    assert GitHubScraper().parse(payload)[0].location == "Austin, TX, United States"


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps(
        {
            "jobs": [
                {"data": {"slug": "1", "title": "Kept"}},
                {"data": {"slug": "2"}},
                {"data": {"title": "No id"}},
                {"not_data": {"slug": "4", "title": "Wrong envelope"}},
                "not-a-dict",
            ]
        }
    )
    assert [j.job_id for j in GitHubScraper().parse(payload)] == ["1"]


def test_empty_board_parses_to_no_jobs():
    assert GitHubScraper().parse(json.dumps({"jobs": []})) == []


def test_a_short_page_ends_pagination():
    scraper = GitHubScraper()
    payload = FIXTURE.read_text(encoding="utf-8")  # 71 < PAGE_SIZE
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_pagination_advances_while_more_remain():
    scraper = GitHubScraper()
    payload = json.dumps(
        {"jobs": [{"data": {"slug": str(i), "title": "x"}} for i in range(PAGE_SIZE)],
         "totalCount": PAGE_SIZE * 3}
    )
    assert "page=2" in scraper.next_page_url(payload, scraper.config.career_url)


def test_page_size_stays_within_the_api_cap():
    # A limit above 100 is rejected with a 422.
    assert PAGE_SIZE <= 100
    assert f"limit={PAGE_SIZE}" in GitHubScraper.config.career_url


def test_scraper_is_a_plain_get():
    assert GitHubScraper.config.fetch_mode is FetchMode.STATIC
