from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.sentinelone import SentinelOneScraper

FIXTURE = Path(__file__).parent / "fixtures" / "sentinelone_jobs.html"


def row(job_id: str, title: str, location: str, department: str = "Sales") -> str:
    """The markup SentinelOne renders per posting: a wide-screen grid of
    title/location/department, then a narrow-screen copy carrying the link."""
    return (
        '<div class="text-left text-[15px] leading-normal bg-light_grey cursor-pointer">'
        '<div class="hidden md:grid md:grid-cols-7">'
        f'<div class="col-span-3 px-4 py-3.5">{title}</div>'
        f'<div class="col-span-2 px-4 py-3.5">{location}</div>'
        f'<div class="col-span-2 px-4 py-3.5">{department}</div>'
        "</div>"
        '<div class="mobile-col flex flex-col px-4 py-3.5 md:hidden">'
        f'<div><a href="/jobs/?gh_jid={job_id}" class="text-sentinel_purple">{title}</a></div>'
        f'<div class="text-[15px] text-black">{location} • {department}</div>'
        "</div></div>"
    )


@pytest.fixture(scope="module")
def sentinelone_jobs():
    return SentinelOneScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(sentinelone_jobs):
    assert len(sentinelone_jobs) == 217
    assert len({j.job_id for j in sentinelone_jobs}) == 217


def test_a_posting_rendered_twice_is_reported_once():
    # Every row renders for both wide and narrow screens. Counting elements
    # rather than ids would double the board.
    jobs = SentinelOneScraper().parse(row("1", "Engineer", "Remote") * 2)
    assert [j.job_id for j in jobs] == ["1"]


def test_job_id_is_the_greenhouse_id_and_appears_in_the_url(sentinelone_jobs):
    for job in sentinelone_jobs:
        assert job.job_id.isdigit()
        assert job.url.endswith(f"gh_jid={job.job_id}")


def test_url_opens_the_posting_rather_than_the_listing(sentinelone_jobs):
    # This board's own gh_jid link does deep-link, which is why it needs no
    # substitute the way the boards in EMBED_FALLBACK_BOARDS do.
    assert all(j.url.startswith("https://www.sentinelone.com/jobs/?gh_jid=") for j in sentinelone_jobs)


def test_every_posting_has_a_title_and_location(sentinelone_jobs):
    assert all(j.title for j in sentinelone_jobs)
    assert all(j.location for j in sentinelone_jobs)


def test_location_comes_from_the_grid_not_the_bullet_list():
    # The narrow-screen copy runs location and department together behind a
    # bullet; reading that one would append "• Sales" to every location.
    jobs = SentinelOneScraper().parse(row("1", "Engineer", "Berlin, Germany", "Engineering"))
    assert jobs[0].location == "Berlin, Germany"


def test_html_entities_in_a_title_are_decoded():
    jobs = SentinelOneScraper().parse(row("1", "Account Executive, SMB - GA &amp; TN", "Georgia"))
    assert jobs[0].title == "Account Executive, SMB - GA & TN"


def test_links_without_a_job_id_are_ignored():
    payload = '<a href="/careers/">Careers</a>' + row("1", "Engineer", "Remote")
    assert [j.job_id for j in SentinelOneScraper().parse(payload)] == ["1"]


def test_a_link_with_no_text_is_skipped():
    payload = '<a href="/jobs/?gh_jid=99"></a>' + row("1", "Engineer", "Remote")
    assert [j.job_id for j in SentinelOneScraper().parse(payload)] == ["1"]


def test_a_posting_outside_a_row_still_parses_without_a_location():
    payload = '<div><a href="/jobs/?gh_jid=42">Engineer</a></div>'
    (job,) = SentinelOneScraper().parse(payload)
    assert job.job_id == "42"
    assert job.location is None


def test_no_posted_date_is_claimed(sentinelone_jobs):
    assert all(j.posted_date is None for j in sentinelone_jobs)


def test_an_empty_page_parses_to_no_jobs():
    assert SentinelOneScraper().parse("<html><body></body></html>") == []


def test_config_reads_the_listing_over_plain_http():
    config = SentinelOneScraper().config
    assert config.name == "SentinelOne"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.career_url == "https://www.sentinelone.com/jobs/"
