from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.twosigma import PAGE_SIZE, TwoSigmaScraper

FIXTURE = Path(__file__).parent / "fixtures" / "twosigma_jobs.html"


@pytest.fixture(scope="module")
def twosigma_jobs():
    return TwoSigmaScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_a_full_page(twosigma_jobs):
    assert len(twosigma_jobs) == PAGE_SIZE
    assert len({j.job_id for j in twosigma_jobs}) == PAGE_SIZE


def test_job_id_comes_from_the_posting_path(twosigma_jobs):
    for job in twosigma_jobs:
        assert job.job_id.isdigit()
        assert job.url.endswith(f"/{job.job_id}")


def test_every_card_has_a_location(twosigma_jobs):
    assert all(j.location for j in twosigma_jobs)


def test_location_is_the_first_info_span_not_the_department():
    html = """
    <div class="article__header__text">
      <h3><a href="/careers/JobDetail/x/99">Engineer</a></h3>
      <div class="article__header__content">
        <div class="article__header__content__text">
          <span class="paragraph_inner-span">United States - NY New York</span>
          <div class="article__header__content__sub-text">
            <span class="paragraph_inner-span">Quantitative Research</span>
          </div>
        </div>
      </div>
    </div>
    """
    job = TwoSigmaScraper().parse(html)[0]
    assert job.location == "United States - NY New York"


def test_board_exposes_no_posting_date(twosigma_jobs):
    assert all(j.posted_date is None for j in twosigma_jobs)


def test_board_is_read_in_full_because_it_is_not_ordered_by_recency():
    # Cards carry no date, so newest-first ordering cannot be confirmed; the
    # board is small enough that reading every page is cheap.
    assert TwoSigmaScraper.config.paginate_fully is True


def test_browser_accept_header_is_sent():
    # A bare User-Agent gets a response with no listings in it.
    assert "Accept" in TwoSigmaScraper.config.request_headers


def test_non_job_links_are_ignored():
    html = '<a href="/careers/Home">Home</a><a href="/careers/JobDetail/x/7">Real</a>'
    assert [j.job_id for j in TwoSigmaScraper().parse(html)] == ["7"]


def test_duplicate_links_within_a_page_are_collapsed():
    html = ('<a href="/careers/JobDetail/x/7">Real</a>' * 2)
    assert len(TwoSigmaScraper().parse(html)) == 1


def test_empty_page_parses_to_no_jobs():
    assert TwoSigmaScraper().parse("<html></html>") == []


def test_a_short_page_ends_pagination():
    scraper = TwoSigmaScraper()
    html = '<a href="/careers/JobDetail/x/7">Real</a>'
    assert scraper.next_page_url(html, scraper.config.career_url) is None


def test_pagination_advances_the_offset(twosigma_jobs):
    scraper = TwoSigmaScraper()
    nxt = scraper.next_page_url(FIXTURE.read_text(encoding="utf-8"), scraper.config.career_url)
    assert parse_qs(urlsplit(nxt).query)["jobOffset"] == [str(PAGE_SIZE)]


def test_scraper_is_a_plain_get():
    assert TwoSigmaScraper.config.fetch_mode is FetchMode.STATIC
