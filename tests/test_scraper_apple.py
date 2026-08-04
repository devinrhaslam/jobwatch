from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from jobwatch.models import FetchMode
from jobwatch.scrapers.apple import (
    PAGE_SIZE,
    SOFTWARE_SUBTEAMS,
    AppleScraper,
    _posted_date,
)

FIXTURE = Path(__file__).parent / "fixtures" / "apple_jobs.html"


@pytest.fixture(scope="module")
def apple_jobs():
    return AppleScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_a_full_page(apple_jobs):
    assert len(apple_jobs) == PAGE_SIZE
    assert len({j.job_id for j in apple_jobs}) == PAGE_SIZE


def test_job_id_comes_from_the_href(apple_jobs):
    # Filtered pages suffix the id ("200674969-0351"); unfiltered ones do not.
    for job in apple_jobs:
        assert job.job_id[0].isdigit()
        assert job.job_id in job.url


def test_job_url_is_absolute(apple_jobs):
    assert all(j.url.startswith("https://jobs.apple.com/") for j in apple_jobs)


def test_every_card_carries_a_date_and_location(apple_jobs):
    assert all(j.posted_date and len(j.posted_date) == 10 for j in apple_jobs)
    assert all(j.location for j in apple_jobs)


def test_posted_date_parses_the_card_format():
    assert _posted_date("Aug 04, 2026") == "2026-08-04"
    assert _posted_date("December 15, 2025") == "2025-12-15"


def test_unparseable_posted_date_is_left_unset():
    assert _posted_date("recently") is None
    assert _posted_date("") is None


def test_entry_url_narrows_by_team_code_pairs():
    # Unfiltered, the board is retail-only, so narrowing is mandatory. Only the
    # code pair form filters; a label slug is silently ignored, and `search`
    # does nothing while additionally breaking pagination.
    url = AppleScraper.config.career_url
    assert "sort=newest" in url
    assert "team=SFTWR-CLD" in url
    assert url.count("team=") == len(SOFTWARE_SUBTEAMS)
    assert "search=" not in url
    assert "keyword=" not in url


def test_pagination_preserves_every_team_parameter():
    # Collapsing the repeated team filter would silently widen the search back
    # to the retail-only board.
    scraper = AppleScraper()
    nxt = scraper.next_page_url(FIXTURE.read_text(encoding="utf-8"), scraper.config.career_url)
    assert nxt.count("team=") == len(SOFTWARE_SUBTEAMS)


def test_location_drops_the_screen_reader_label():
    html = """
    <div class="job-list-item">
      <a href="/en-us/details/1-22/a">A</a>
      <div class="job-title-location"><span class="a11y">Location</span><span>Cupertino</span></div>
    </div>
    """
    assert AppleScraper().parse(html)[0].location == "Cupertino"


def test_cards_without_a_job_link_are_skipped():
    html = """
    <div class="job-list-item"><a href="/en-us/details/1/kept">Kept</a></div>
    <div class="job-list-item"><a href="/en-us/about">Not a job</a></div>
    <div class="job-list-item"><span>No link at all</span></div>
    """
    assert [j.job_id for j in AppleScraper().parse(html)] == ["1"]


def test_duplicate_ids_within_a_page_are_collapsed():
    html = """
    <div class="job-list-item"><a href="/en-us/details/1/a">A</a></div>
    <div class="job-list-item"><a href="/en-us/details/1/a">A</a></div>
    """
    assert len(AppleScraper().parse(html)) == 1


def test_missing_date_and_location_are_left_unset():
    html = '<div class="job-list-item"><a href="/en-us/details/1/a">A</a></div>'
    job = AppleScraper().parse(html)[0]
    assert job.posted_date is None
    assert job.location is None


def test_empty_page_parses_to_no_jobs():
    assert AppleScraper().parse("<html><body></body></html>") == []


def test_a_short_page_ends_pagination():
    scraper = AppleScraper()
    html = '<div class="job-list-item"><a href="/en-us/details/1/a">A</a></div>'
    assert scraper.next_page_url(html, scraper.config.career_url) is None


def test_pagination_advances_on_a_full_page():
    scraper = AppleScraper()
    nxt = scraper.next_page_url(FIXTURE.read_text(encoding="utf-8"), scraper.config.career_url)
    assert "page=2" in nxt
    assert "sort=newest" in nxt


def test_scraper_is_a_plain_get():
    assert AppleScraper.config.fetch_mode is FetchMode.STATIC
