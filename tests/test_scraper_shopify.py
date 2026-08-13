from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.shopify import ShopifyScraper, _title_from_slug

FIXTURE = Path(__file__).parent / "fixtures" / "shopify_careers_sitemap.xml"


@pytest.fixture(scope="module")
def jobs():
    return ShopifyScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_sitemap(jobs):
    assert len(jobs) == 109
    assert len({j.job_id for j in jobs}) == 109


def test_every_sitemap_entry_is_a_posting(jobs):
    # The careers sitemap holds only job URLs — no marketing pages — so a drop
    # in this count means postings went missing, not that filtering improved.
    assert all(j.url.startswith("https://www.shopify.com/careers/") for j in jobs)


def test_job_id_is_the_uuid_and_appears_in_the_url(jobs):
    for job in jobs:
        assert len(job.job_id) == 36 and job.job_id.count("-") == 4
        assert job.url.endswith(f"_{job.job_id}")


def test_location_and_posted_date_are_unset(jobs):
    # The sitemap carries neither; see the scraper docstring for why lastmod is
    # not reported as a posting date.
    assert all(j.location is None for j in jobs)
    assert all(j.posted_date is None for j in jobs)


def test_titles_are_recovered_from_the_slug(jobs):
    assert all(j.title and j.title[0].isupper() for j in jobs)
    assert not any("-" in j.title for j in jobs)
    assert not any("_" in j.title for j in jobs)


def test_acronyms_survive_title_casing():
    # A plain .capitalize() would render these "Smb" and "Uk", which reads as a
    # typo in a report.
    assert _title_from_slug("account-executive-smb") == "Account Executive SMB"
    assert _title_from_slug("senior-lead-uk-public-affairs") == (
        "Senior Lead UK Public Affairs"
    )
    assert _title_from_slug("applied-ml-engineer") == "Applied ML Engineer"


def test_ordinary_words_are_capitalised_not_uppercased():
    assert _title_from_slug("staff-software-engineer") == "Staff Software Engineer"


def test_two_postings_of_the_same_role_stay_distinct(jobs):
    # Shopify lists duplicate titles under different uuids (two "Account
    # Executive SMB"); they are separate postings and must not collapse.
    titles = [j.title for j in jobs]
    assert titles.count("Account Executive SMB") >= 2
    duplicates = [j for j in jobs if j.title == "Account Executive SMB"]
    assert len({j.job_id for j in duplicates}) == len(duplicates)


def test_repeated_sitemap_entries_are_reported_once():
    payload = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://www.shopify.com/careers/eng_11111111-1111-1111-1111-111111111111</loc></url>"
        "<url><loc>https://www.shopify.com/careers/eng_11111111-1111-1111-1111-111111111111</loc></url>"
        "<url><loc>https://www.shopify.com/careers/pm_22222222-2222-2222-2222-222222222222</loc></url>"
        "</urlset>"
    )
    assert [j.title for j in ShopifyScraper().parse(payload)] == ["Eng", "Pm"]


def test_non_job_urls_are_ignored():
    payload = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://www.shopify.com/careers/extraordinary</loc></url>"
        "<url><loc>https://www.shopify.com/careers/product-principles</loc></url>"
        "<url><loc>https://www.shopify.com/careers/eng_11111111-1111-1111-1111-111111111111</loc></url>"
        "</urlset>"
    )
    assert [j.job_id for j in ShopifyScraper().parse(payload)] == [
        "11111111-1111-1111-1111-111111111111"
    ]


def test_empty_sitemap_yields_no_jobs():
    payload = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    )
    assert ShopifyScraper().parse(payload) == []


def test_config_targets_the_careers_sitemap():
    config = ShopifyScraper().config
    assert config.name == "Shopify"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.career_url == "https://www.shopify.com/careers/sitemap.xml"
