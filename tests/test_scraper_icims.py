from pathlib import Path

import pytest

from jobwatch.models import FetchMode, Job
from jobwatch.scrapers.icims import BOARDS, ICIMSScraper, scrapers

FIXTURES = Path(__file__).parent / "fixtures"
SITEMAP_FIXTURE = FIXTURES / "icims_joby_sitemap.xml"
DETAIL_FIXTURE = FIXTURES / "icims_joby_job_detail.html"

HOST = "https://careers-jobyaviation.icims.com"
SITEMAP_HEAD = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'


def sitemap(*locs: str) -> str:
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f"{SITEMAP_HEAD}{entries}</urlset>"


def scraper() -> ICIMSScraper:
    return ICIMSScraper("Joby Aviation", HOST)


@pytest.fixture(scope="module")
def joby_jobs():
    return scraper().parse(SITEMAP_FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(joby_jobs):
    assert len(joby_jobs) == 240
    assert len({j.job_id for j in joby_jobs}) == 240


def test_job_id_is_the_numeric_path_id(joby_jobs):
    for job in joby_jobs:
        assert job.job_id.isdigit()
        assert f"/jobs/{job.job_id}/" in job.url


def test_the_intro_page_is_not_parsed_as_a_job(joby_jobs):
    # The sitemap lists /jobs/intro, which has no id and no title.
    assert not any(j.url.endswith("/jobs/intro") for j in joby_jobs)


def test_title_from_the_slug_is_percent_decoded():
    payload = sitemap(f"{HOST}/jobs/5293/quality-inspector%2c-mechanical-assemblies/job")
    (job,) = scraper().parse(payload)
    assert job.title == "quality inspector, mechanical assemblies"


def test_a_repeated_posting_is_reported_once():
    url = f"{HOST}/jobs/5306/events-manager/job"
    assert len(scraper().parse(sitemap(url, url))) == 1


def test_listing_carries_no_location_or_posted_date(joby_jobs):
    assert all(j.location is None for j in joby_jobs)
    assert all(j.posted_date is None for j in joby_jobs)


def test_detail_url_asks_for_the_iframe_content():
    # The posting page is a shell; its content lives in an iframe at the same
    # URL with this parameter, and only that carries the JobPosting.
    job = Job(company="Joby Aviation", job_id="5306", title="events manager",
              url=f"{HOST}/jobs/5306/events-manager/job")
    assert scraper().detail_url(job) == f"{HOST}/jobs/5306/events-manager/job?in_iframe=1"


def test_detail_url_appends_to_an_existing_query():
    job = Job(company="Joby Aviation", job_id="1", title="x", url=f"{HOST}/jobs/1/x/job?a=b")
    assert scraper().detail_url(job).endswith("?a=b&in_iframe=1")


def test_enrichment_replaces_the_slug_title_with_the_real_one():
    job = Job(company="Joby Aviation", job_id="5306", title="events manager",
              url=f"{HOST}/jobs/5306/events-manager/job")
    enriched = scraper().parse_detail(DETAIL_FIXTURE.read_text(encoding="utf-8"), job)
    assert enriched.title == "Events Manager"
    assert enriched.job_id == job.job_id
    assert enriched.url == job.url


def test_enrichment_lists_every_locality_the_posting_names():
    job = Job(company="Joby Aviation", job_id="5306", title="events manager",
              url=f"{HOST}/jobs/5306/events-manager/job")
    enriched = scraper().parse_detail(DETAIL_FIXTURE.read_text(encoding="utf-8"), job)
    assert enriched.location.startswith("Santa Cruz")
    assert "New York" in enriched.location


def test_unavailable_localities_are_dropped():
    # iCIMS fills unknown address fields with the literal string UNAVAILABLE.
    payload = (
        '<script type="application/ld+json">'
        '{"title":"Engineer","jobLocation":['
        '{"address":{"addressLocality":"UNAVAILABLE"}},'
        '{"address":{"addressLocality":"Marina"}}]}'
        "</script>"
    )
    job = Job(company="Joby Aviation", job_id="1", title="engineer", url=f"{HOST}/jobs/1/e/job")
    assert scraper().parse_detail(payload, job).location == "Marina"


def test_enrichment_never_sets_a_posted_date():
    # The JobPosting carries a datePosted, but it is generated per request:
    # every posting reports exactly two years before the moment it was fetched.
    job = Job(company="Joby Aviation", job_id="5306", title="events manager",
              url=f"{HOST}/jobs/5306/events-manager/job")
    enriched = scraper().parse_detail(DETAIL_FIXTURE.read_text(encoding="utf-8"), job)
    assert enriched.posted_date is None


def test_a_page_without_a_job_posting_leaves_the_job_untouched():
    job = Job(company="Joby Aviation", job_id="1", title="engineer", url=f"{HOST}/jobs/1/e/job")
    assert scraper().parse_detail("<html>no ld+json here</html>", job) is job


def test_every_board_becomes_a_static_scraper():
    built = scrapers()
    assert len(built) == len(BOARDS)
    assert all(s.config.fetch_mode is FetchMode.STATIC for s in built)
    assert all(s.config.career_url.endswith("/sitemap.xml") for s in built)
    assert {s.config.name for s in built} == set(BOARDS)
