from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.zed import ZedScraper

FIXTURE = Path(__file__).parent / "fixtures" / "zed_jobs.html"


@pytest.fixture(scope="module")
def zed_jobs():
    return ZedScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_the_openings_in_the_fixture(zed_jobs):
    assert len(zed_jobs) == 2
    assert {j.job_id for j in zed_jobs} == {"open-source-engineer", "product-designer"}


def test_title_comes_from_the_anchor_text(zed_jobs):
    titles = {j.job_id: j.title for j in zed_jobs}
    assert titles["open-source-engineer"] == "Open Source Engineer"
    # The slug and the title disagree here, which is why the anchor text is read
    # rather than the slug being prettified.
    assert titles["product-designer"] == "Product Design Engineer"


def test_url_is_built_from_the_slug(zed_jobs):
    for job in zed_jobs:
        assert job.url == f"https://zed.dev/jobs/{job.job_id}"


def test_the_jobs_index_itself_is_not_a_posting():
    payload = '<a href="/jobs">Jobs</a><a href="/jobs/engineer">Engineer</a>'
    assert [j.job_id for j in ZedScraper().parse(payload)] == ["engineer"]


def test_section_fragments_are_not_postings():
    payload = (
        '<a href="/jobs#open-positions">Open Positions</a>'
        '<a href="/jobs#perks-and-benefits">Perks</a>'
        '<a href="/jobs/engineer">Engineer</a>'
    )
    assert [j.job_id for j in ZedScraper().parse(payload)] == ["engineer"]


def test_a_deeper_path_is_not_a_posting():
    payload = '<a href="/jobs/engineer/apply">Apply</a><a href="/jobs/engineer">Engineer</a>'
    assert [j.job_id for j in ZedScraper().parse(payload)] == ["engineer"]


def test_a_repeated_link_is_reported_once():
    payload = '<a href="/jobs/engineer">Engineer</a><a href="/jobs/engineer">Engineer</a>'
    assert len(ZedScraper().parse(payload)) == 1


def test_a_link_with_no_text_is_skipped():
    payload = '<a href="/jobs/ghost"></a><a href="/jobs/engineer">Engineer</a>'
    assert [j.job_id for j in ZedScraper().parse(payload)] == ["engineer"]


def test_no_location_or_posted_date_is_claimed(zed_jobs):
    assert all(j.location is None for j in zed_jobs)
    assert all(j.posted_date is None for j in zed_jobs)


def test_a_page_with_no_openings_parses_to_no_jobs():
    assert ZedScraper().parse("<html><body>No open roles</body></html>") == []


def test_config_reads_the_listing_over_plain_http():
    config = ZedScraper().config
    assert config.name == "Zed"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.career_url == "https://zed.dev/jobs"
