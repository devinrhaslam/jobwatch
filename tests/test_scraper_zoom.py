from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.zoom import ZoomScraper

FIXTURE = Path(__file__).parent / "fixtures" / "zoom_sitemap.xml"
HEAD = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'


def sitemap(*locs):
    return HEAD + "".join(f"<url><loc>{l}</loc></url>" for l in locs) + "</urlset>"


@pytest.fixture(scope="module")
def zoom_jobs():
    return ZoomScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_the_postings_in_the_fixture(zoom_jobs):
    assert len(zoom_jobs) > 100
    assert len({j.job_id for j in zoom_jobs}) == len(zoom_jobs)


def test_only_job_urls_are_parsed(zoom_jobs):
    assert all("/jobs/" in j.url for j in zoom_jobs)


def test_a_trailing_uuid_is_not_part_of_the_title():
    payload = sitemap(
        "https://careers.zoom.us/jobs/staff-ai-engineer-seattle-washington-united-states"
        "-89f5371c-16e9-43fe-b7ae-7878c5766c44"
    )
    (job,) = ZoomScraper().parse(payload)
    assert job.title == "staff ai engineer seattle washington united states"


def test_a_slug_without_a_uuid_keeps_all_of_its_words():
    payload = sitemap("https://careers.zoom.us/jobs/upmarket-account-executive-tokyo-japan")
    (job,) = ZoomScraper().parse(payload)
    assert job.title == "upmarket account executive tokyo japan"


def test_a_hex_looking_word_that_is_not_a_uuid_is_kept():
    payload = sitemap("https://careers.zoom.us/jobs/engineer-abcdef12")
    (job,) = ZoomScraper().parse(payload)
    assert job.title == "engineer abcdef12"


def test_job_id_is_the_slug_and_appears_in_the_url(zoom_jobs):
    for job in zoom_jobs:
        assert job.url.rstrip("/").endswith(job.job_id)


def test_non_job_urls_are_ignored():
    payload = sitemap(
        "https://careers.zoom.us/",
        "https://careers.zoom.us/pages/life-at-zoom",
        "https://careers.zoom.us/jobs/engineer-boston",
    )
    assert [j.job_id for j in ZoomScraper().parse(payload)] == ["engineer-boston"]


def test_a_repeated_posting_is_reported_once():
    url = "https://careers.zoom.us/jobs/engineer-boston"
    assert len(ZoomScraper().parse(sitemap(url, url))) == 1


def test_no_location_or_posted_date_is_claimed(zoom_jobs):
    # The location is inside the title slug and cannot be split back out; the
    # sitemap's lastmod is a modification time.
    assert all(j.location is None for j in zoom_jobs)
    assert all(j.posted_date is None for j in zoom_jobs)


def test_config_reads_the_sitemap_and_records_the_stated_crawl_delay():
    config = ZoomScraper().config
    assert config.name == "Zoom"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.career_url.endswith("sitemap.xml")
    assert config.inter_page_delay_seconds == 5.0
