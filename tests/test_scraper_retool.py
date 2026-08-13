from pathlib import Path

import pytest

from jobwatch.models import FetchMode, Job
from jobwatch.scrapers.retool import RetoolScraper

FIXTURES = Path(__file__).parent / "fixtures"
SITEMAP_FIXTURE = FIXTURES / "retool_sitemap.xml"
DETAIL_FIXTURE = FIXTURES / "retool_job_detail.html"

SITEMAP_HEAD = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'


def sitemap(*locs: str) -> str:
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f"{SITEMAP_HEAD}{entries}</urlset>"


@pytest.fixture(scope="module")
def retool_jobs():
    return RetoolScraper().parse(SITEMAP_FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(retool_jobs):
    assert len(retool_jobs) == 37
    assert len({j.job_id for j in retool_jobs}) == 37


def test_only_career_pages_with_all_three_slug_parts_are_jobs(retool_jobs):
    # The sitemap carries the whole marketing site; a job is a /careers/ URL
    # whose slug is title--department--location.
    for job in retool_jobs:
        assert "/careers/" in job.url
        assert job.job_id.count("--") == 2


def test_the_careers_index_is_not_a_job():
    payload = sitemap(
        "https://retool.com/careers",
        "https://retool.com/careers/data-scientist--data-science--san-francisco-united-states",
    )
    jobs = RetoolScraper().parse(payload)
    assert [j.title for j in jobs] == ["data scientist"]


def test_unrelated_pages_are_ignored():
    payload = sitemap(
        "https://retool.com/blog/some-post",
        "https://retool.com/pricing",
        "https://retool.com/careers/engineer--engineering--london-united-kingdom",
    )
    assert len(RetoolScraper().parse(payload)) == 1


def test_title_and_location_come_from_the_slug():
    payload = sitemap(
        "https://retool.com/careers/data-scientist--data-science--san-francisco-united-states"
    )
    (job,) = RetoolScraper().parse(payload)
    assert job.title == "data scientist"
    assert job.location == "san francisco united states"


def test_a_title_ending_in_a_hyphen_does_not_leak_into_the_next_part():
    # "…-ai-product-engineer-" followed by "--engineering" reads as three
    # hyphens in a row; without trimming, the department would parse as
    # "-engineering" and the title would keep a trailing space.
    payload = sitemap(
        "https://retool.com/careers/software-engineer-ai-product-engineer---engineering--san-francisco-united-states"
    )
    (job,) = RetoolScraper().parse(payload)
    assert job.title == "software engineer ai product engineer"
    assert job.location == "san francisco united states"


def test_a_repeated_url_is_reported_once():
    url = "https://retool.com/careers/engineer--engineering--london-united-kingdom"
    assert len(RetoolScraper().parse(sitemap(url, url))) == 1


def test_job_id_is_the_slug_and_appears_in_the_url(retool_jobs):
    for job in retool_jobs:
        assert job.url.endswith(job.job_id)


def test_no_posted_date_is_claimed(retool_jobs):
    # Neither the sitemap nor the page publishes one; lastmod is a modification
    # time rather than a publication time.
    assert all(j.posted_date is None for j in retool_jobs)


def test_enrichment_recovers_the_real_capitalisation_and_punctuation():
    job = Job(
        company="Retool",
        job_id="software-engineer-observability--engineering--san-francisco-united-states",
        title="software engineer observability",
        url="https://retool.com/careers/software-engineer-observability--engineering--san-francisco-united-states",
        location="san francisco united states",
    )
    enriched = RetoolScraper().parse_detail(
        DETAIL_FIXTURE.read_text(encoding="utf-8"), job
    )
    assert enriched.title == "Software Engineer, Observability"
    assert enriched.location == job.location
    assert enriched.url == job.url


def test_enrichment_strips_only_the_site_suffix():
    job = Job(company="Retool", job_id="a--b--c", title="x", url="https://retool.com/careers/a--b--c")
    enriched = RetoolScraper().parse_detail("<title>Retool Engineer | Retool</title>", job)
    assert enriched.title == "Retool Engineer"


def test_a_page_without_a_title_leaves_the_job_untouched():
    job = Job(company="Retool", job_id="a--b--c", title="x", url="https://retool.com/careers/a--b--c")
    assert RetoolScraper().parse_detail("<html><body>nothing</body></html>", job) is job


def test_detail_url_is_the_posting_itself():
    job = Job(company="Retool", job_id="a--b--c", title="x", url="https://retool.com/careers/a--b--c")
    assert RetoolScraper().detail_url(job) == job.url


def test_config_is_the_sitemap_over_plain_http():
    config = RetoolScraper().config
    assert config.name == "Retool"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.career_url.endswith("sitemap.xml")
