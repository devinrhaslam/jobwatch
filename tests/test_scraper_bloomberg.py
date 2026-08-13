from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.bloomberg import BloombergScraper

FIXTURE = Path(__file__).parent / "fixtures" / "bloomberg_avature_sitemap.xml"


@pytest.fixture(scope="module")
def jobs():
    return BloombergScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_sitemap(jobs):
    assert len(jobs) == 405
    assert len({j.job_id for j in jobs}) == 405


def test_non_job_sitemap_entries_are_ignored(jobs):
    # The sitemap holds 445 URLs, only 405 of which are postings; the rest are
    # portal pages that must not be reported as jobs.
    assert all("/careers/JobDetail/" in j.url for j in jobs)


def test_job_id_is_the_trailing_number(jobs):
    assert all(j.job_id.isdigit() for j in jobs)
    assert all(j.url.endswith(f"/{j.job_id}") for j in jobs)


def test_titles_keep_avature_capitalisation(jobs):
    # Avature slugs preserve the original casing, so "iOS" must survive rather
    # than being title-cased into "Ios".
    titles = [j.title for j in jobs]
    assert "Senior iOS Engineer Mobile Professional" in titles
    assert not any("-" in t for t in titles)


def test_location_and_posted_date_are_unset(jobs):
    assert all(j.location is None for j in jobs)
    assert all(j.posted_date is None for j in jobs)


def test_slug_with_internal_hyphens_keeps_the_trailing_id():
    payload = _sitemap(
        ["https://bloomberg.avature.net/careers/JobDetail/Team-Lead-Product-Management/21238"]
    )
    job = BloombergScraper().parse(payload)[0]
    assert job.job_id == "21238"
    assert job.title == "Team Lead Product Management"


def test_repeated_entries_are_reported_once():
    payload = _sitemap(
        [
            "https://bloomberg.avature.net/careers/JobDetail/Engineer/1",
            "https://bloomberg.avature.net/careers/JobDetail/Engineer/1",
            "https://bloomberg.avature.net/careers/JobDetail/Designer/2",
        ]
    )
    assert [j.job_id for j in BloombergScraper().parse(payload)] == ["1", "2"]


def test_portal_urls_without_a_job_id_are_skipped():
    payload = _sitemap(
        [
            "https://bloomberg.avature.net/careers",
            "https://bloomberg.avature.net/careers/SearchJobs",
            "https://bloomberg.avature.net/careers/JobDetail/Engineer/7",
        ]
    )
    assert [j.job_id for j in BloombergScraper().parse(payload)] == ["7"]


def test_empty_sitemap_yields_no_jobs():
    assert BloombergScraper().parse(_sitemap([])) == []


def test_config_reads_the_avature_sitemap_not_the_blocked_host():
    config = BloombergScraper().config
    assert config.name == "Bloomberg"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.career_url == "https://bloomberg.avature.net/careers/sitemap.xml"
    # careers.bloomberg.com serves a bot challenge and must not be used.
    assert "careers.bloomberg.com" not in config.career_url


def _sitemap(locs):
    body = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{body}</urlset>"
    )
