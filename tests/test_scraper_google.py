from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from jobwatch.models import FetchMode
from jobwatch.scrapers.google import (
    PAGE_SIZE,
    GoogleDeepMindScraper,
    GoogleScraper,
    _location,
)

FIXTURE = Path(__file__).parent / "fixtures" / "google_jobs.html"
DEEPMIND_FIXTURE = Path(__file__).parent / "fixtures" / "google_deepmind_jobs.html"


@pytest.fixture(scope="module")
def google_jobs():
    return GoogleScraper().parse(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def deepmind_jobs():
    return GoogleDeepMindScraper().parse(DEEPMIND_FIXTURE.read_text(encoding="utf-8"))


def test_parses_a_full_page(google_jobs):
    assert len(google_jobs) == PAGE_SIZE
    assert len({j.job_id for j in google_jobs}) == PAGE_SIZE


def test_job_id_comes_from_the_href_not_a_class_name(google_jobs):
    # BOQ class names are build-generated; the href pattern is stable.
    for job in google_jobs:
        assert job.job_id.isdigit()
        assert job.job_id in job.url


def test_job_url_is_absolute(google_jobs):
    assert all(j.url.startswith("https://www.google.com/") for j in google_jobs)


def test_titles_are_populated(google_jobs):
    assert all(j.title for j in google_jobs)


def test_board_exposes_no_posting_date(google_jobs):
    # Cards carry no date; recency comes from snapshot diffing, and sort_by=date
    # in the entry URL is what keeps the engine's early stop safe.
    assert all(j.posted_date is None for j in google_jobs)
    assert "sort_by=date" in GoogleScraper.config.career_url


def test_entry_url_narrows_at_source():
    assert "q=software+engineer" in GoogleScraper.config.career_url


def test_location_is_read_from_the_place_icon_span():
    html = """
    <li ssk="18:1">
      <a href="/about/careers/applications/jobs/results/1-x">x</a>
      <h3>Software Engineer</h3>
      <span><i>place</i>Mountain View, CA, USA</span>
    </li>
    """
    card = BeautifulSoup(html, "html.parser").select("li[ssk]")[0]
    assert _location(card) == "Mountain View, CA, USA"


def test_more_locations_affordance_is_stripped():
    html = """
    <li ssk="18:1">
      <span><i>place</i>Austin, TX, USA + 3 more locations</span>
    </li>
    """
    card = BeautifulSoup(html, "html.parser").select("li[ssk]")[0]
    assert _location(card) == "Austin, TX, USA"


def test_card_without_a_place_icon_has_no_location():
    html = '<li ssk="18:1"><span><i>corporate_fare</i>Google</span></li>'
    card = BeautifulSoup(html, "html.parser").select("li[ssk]")[0]
    assert _location(card) is None


def test_cards_missing_a_link_or_heading_are_skipped():
    html = """
    <ul>
      <li ssk="18:1"><a href="/jobs/results/1-kept">x</a><h3>Kept</h3></li>
      <li ssk="18:2"><h3>No link</h3></li>
      <li ssk="18:3"><a href="/jobs/results/3-x">x</a></li>
      <li ssk="18:4"><a href="/about/help">no job id</a><h3>Not a job</h3></li>
    </ul>
    """
    assert [j.job_id for j in GoogleScraper().parse(html)] == ["1"]


def test_duplicate_ids_within_a_page_are_collapsed():
    html = """
    <ul>
      <li ssk="18:1"><a href="/jobs/results/1-a">x</a><h3>A</h3></li>
      <li ssk="18:1"><a href="/jobs/results/1-a">x</a><h3>A</h3></li>
    </ul>
    """
    assert len(GoogleScraper().parse(html)) == 1


def test_empty_page_parses_to_no_jobs():
    assert GoogleScraper().parse("<html><body></body></html>") == []


def test_a_short_page_ends_pagination():
    scraper = GoogleScraper()
    html = '<li ssk="18:1"><a href="/jobs/results/1-a">x</a><h3>A</h3></li>'
    assert scraper.next_page_url(html, scraper.config.career_url) is None


def test_pagination_advances_on_a_full_page(google_jobs):
    scraper = GoogleScraper()
    nxt = scraper.next_page_url(FIXTURE.read_text(encoding="utf-8"), scraper.config.career_url)
    assert "page=2" in nxt
    assert "q=software+engineer" in nxt  # query survives paging


def test_scraper_is_a_plain_get():
    assert GoogleScraper.config.fetch_mode is FetchMode.STATIC


def test_deepmind_parses_a_full_page(deepmind_jobs):
    assert len(deepmind_jobs) == PAGE_SIZE
    assert len({j.job_id for j in deepmind_jobs}) == PAGE_SIZE


def test_deepmind_jobs_are_attributed_to_deepmind_not_google(deepmind_jobs):
    # The shared parse reads the company off its own config; hardcoding
    # "Google" would file every DeepMind posting under the wrong snapshot.
    assert {j.company for j in deepmind_jobs} == {"Google DeepMind"}


def test_deepmind_entry_url_filters_by_company_not_a_keyword():
    # deepmind.google/careers links to `company=DeepMind`; the board is small
    # enough that Google's `q=software engineer` narrowing is not needed.
    url = GoogleDeepMindScraper.config.career_url
    assert "company=DeepMind" in url
    assert "q=" not in url
    assert "sort_by=date" in url  # keeps the engine's early stop safe


def test_deepmind_and_google_are_separate_boards():
    assert GoogleDeepMindScraper.config.name != GoogleScraper.config.name
    assert GoogleDeepMindScraper.config.career_url != GoogleScraper.config.career_url


def test_deepmind_pagination_keeps_the_company_filter(deepmind_jobs):
    scraper = GoogleDeepMindScraper()
    nxt = scraper.next_page_url(
        DEEPMIND_FIXTURE.read_text(encoding="utf-8"), scraper.config.career_url
    )
    assert "page=2" in nxt
    assert "company=DeepMind" in nxt
