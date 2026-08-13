import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode, Job
from jobwatch.scrapers.deelboard import PENDING_TITLE, DeelBoardScraper


def KlarnaScraper():
    """Klarna's board, now one entry in the parameterised Deel-board scraper."""
    return DeelBoardScraper("Klarna", "klarna", 150)

SITEMAP = Path(__file__).parent / "fixtures" / "klarna_sitemap.xml"
DETAIL = Path(__file__).parent / "fixtures" / "klarna_job_detail.html"


@pytest.fixture(scope="module")
def jobs():
    return KlarnaScraper().parse(SITEMAP.read_text(encoding="utf-8"))


def test_sitemap_yields_every_posting(jobs):
    assert len(jobs) == 100
    assert len({j.job_id for j in jobs}) == 100


def test_board_root_url_is_not_treated_as_a_posting(jobs):
    # The sitemap's first entry is the board itself, which has no job id.
    assert all("/job-details/" in j.url for j in jobs)


def test_listing_carries_only_id_and_url(jobs):
    # The sitemap has no titles, locations or dates — that is the whole reason
    # for the enrichment step.
    assert all(j.title == PENDING_TITLE for j in jobs)
    assert all(j.location is None and j.posted_date is None for j in jobs)


def test_job_id_is_the_uuid_from_the_url(jobs):
    for job in jobs:
        assert len(job.job_id) == 36 and job.job_id.count("-") == 4
        assert job.job_id in job.url


def test_detail_url_is_the_posting_itself(jobs):
    scraper = KlarnaScraper()
    assert all(scraper.detail_url(j) == j.url for j in jobs)


def test_detail_page_supplies_title_location_and_date(jobs):
    scraper = KlarnaScraper()
    listing = jobs[0]
    enriched = scraper.parse_detail(DETAIL.read_text(encoding="utf-8"), listing)
    assert enriched.title == (
        "Customer Trust and Experience Consultant (Fully Remote - Sweden)"
    )
    assert enriched.location == "Sweden"
    assert enriched.posted_date == "2026-04-21"
    # Identity must survive enrichment or the diff would treat it as a new job.
    assert enriched.job_id == listing.job_id
    assert enriched.url == listing.url
    assert enriched.company == "Klarna"


def test_job_posting_is_found_among_several_json_ld_blocks():
    # Real pages carry a BreadcrumbList too, and it comes second here — taking
    # the first block would work by luck, so the order is inverted in this test.
    payload = _detail_page(
        [
            {"@type": "BreadcrumbList", "itemListElement": []},
            {"@type": "JobPosting", "title": "Principal Engineer"},
        ]
    )
    job = KlarnaScraper().parse_detail(payload, _listing())
    assert job.title == "Principal Engineer"


def test_page_without_a_job_posting_leaves_the_job_unchanged():
    payload = _detail_page([{"@type": "BreadcrumbList"}])
    job = KlarnaScraper().parse_detail(payload, _listing())
    assert job.title == PENDING_TITLE
    assert job.location is None


def test_unparseable_json_ld_block_is_skipped():
    payload = (
        '<script type="application/ld+json">{not json}</script>'
        + _detail_page([{"@type": "JobPosting", "title": "Engineer"}])
    )
    assert KlarnaScraper().parse_detail(payload, _listing()).title == "Engineer"


def test_multiple_job_locations_are_reported():
    payload = _detail_page(
        [
            {
                "@type": "JobPosting",
                "title": "Engineer",
                "jobLocation": [
                    {"address": {"addressLocality": "Stockholm", "addressCountry": "SE"}},
                    {"address": {"addressLocality": "Berlin", "addressCountry": "DE"}},
                ],
            }
        ]
    )
    job = KlarnaScraper().parse_detail(payload, _listing())
    assert job.location == "Stockholm, SE | Berlin, DE"


def test_single_job_location_object_is_accepted():
    payload = _detail_page(
        [
            {
                "@type": "JobPosting",
                "title": "Engineer",
                "jobLocation": {"address": {"addressLocality": "Stockholm"}},
            }
        ]
    )
    assert KlarnaScraper().parse_detail(payload, _listing()).location == "Stockholm"


def test_unparseable_date_leaves_posted_date_unset():
    payload = _detail_page(
        [{"@type": "JobPosting", "title": "Engineer", "datePosted": "soon"}]
    )
    assert KlarnaScraper().parse_detail(payload, _listing()).posted_date is None


def test_empty_sitemap_yields_no_jobs():
    payload = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    )
    assert KlarnaScraper().parse(payload) == []


def test_config_reads_the_documented_sitemap_not_the_disallowed_api():
    config = KlarnaScraper().config
    assert config.name == "Klarna"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.career_url == "https://jobs.deel.com/klarna/sitemap.xml"
    # Deel's robots.txt disallows /api/.
    assert "/api/" not in config.career_url
    # A seed must be able to enrich the whole board in one run.
    assert config.max_enrichment_fetches >= 100


def _listing():
    return Job(
        company="Klarna",
        job_id="5d3636f8-0712-4fe2-a1f4-84358440d272",
        title=PENDING_TITLE,
        url="https://jobs.deel.com/klarna/job-details/5d3636f8-0712-4fe2-a1f4-84358440d272/overview",
    )


def _detail_page(blocks):
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks
    )
    return f"<html><head>{scripts}</head><body></body></html>"
