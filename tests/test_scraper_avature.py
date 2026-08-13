from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.avature import BOARDS, AvatureScraper, scrapers

FIXTURES = Path(__file__).parent / "fixtures"
SYNOPSYS_FIXTURE = FIXTURES / "avature_synopsys_sitemap.xml"
EA_FIXTURE = FIXTURES / "avature_ea_sitemap.xml"

SYNOPSYS_SITEMAP = "https://synopsys.avature.net/careers/sitemap.xml"
EA_SITEMAP = "https://jobs.ea.com/en_US/careers/sitemap.xml"

SITEMAP_HEAD = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'


def sitemap(*locs: str) -> str:
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f"{SITEMAP_HEAD}{entries}</urlset>"


def parse(payload: str, sitemap_url: str = SYNOPSYS_SITEMAP):
    return AvatureScraper("Synopsys", sitemap_url).parse(payload)


@pytest.fixture(scope="module")
def synopsys_jobs():
    return parse(SYNOPSYS_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ea_jobs():
    return AvatureScraper("Electronic Arts", EA_SITEMAP).parse(
        EA_FIXTURE.read_text(encoding="utf-8")
    )


def test_parses_every_posting_in_the_fixture(synopsys_jobs):
    assert len(synopsys_jobs) == 373
    assert len({j.job_id for j in synopsys_jobs}) == 373


def test_job_id_is_the_trailing_path_id(synopsys_jobs):
    for job in synopsys_jobs:
        assert job.job_id.isdigit()
        assert job.url.endswith(f"/{job.job_id}")


def test_the_bare_job_detail_index_is_not_parsed_as_a_job(synopsys_jobs):
    # The sitemap lists /careers/JobDetail itself. Without the trailing-id
    # requirement it would become a titleless job pointing at a listing page.
    assert not any(j.url.endswith("/careers/JobDetail") for j in synopsys_jobs)


def test_title_drops_the_requisition_id_the_slug_repeats():
    # Synopsys ends the slug with the same id that follows it in the path.
    # Leaving it in would put a bare number on the end of every title.
    payload = sitemap(f"https://synopsys.avature.net/careers/JobDetail/ASIC-Design-Engineer-13113/13113")
    (job,) = parse(payload)
    assert job.title == "ASIC Design Engineer"


def test_a_slug_not_ending_in_the_id_keeps_all_of_its_words():
    payload = sitemap("https://synopsys.avature.net/careers/JobDetail/Senior-iOS-Engineer/4242")
    (job,) = parse(payload)
    assert job.title == "Senior iOS Engineer"


def test_a_number_inside_the_title_is_not_mistaken_for_the_id():
    payload = sitemap("https://synopsys.avature.net/careers/JobDetail/Engineer-Level-3/4242")
    (job,) = parse(payload)
    assert job.title == "Engineer Level 3"


def test_a_repeated_posting_is_reported_once():
    url = "https://synopsys.avature.net/careers/JobDetail/ASIC-Engineer/13113"
    assert len(parse(sitemap(url, url))) == 1


def test_non_posting_urls_are_ignored():
    payload = sitemap(
        "https://synopsys.avature.net/careers/ApplicationForm",
        "https://synopsys.avature.net/careers/JobDetail/Real-Job/1",
    )
    assert [j.job_id for j in parse(payload)] == ["1"]


def test_location_and_posted_date_are_left_unset(synopsys_jobs):
    # A sitemap carries neither, and lastmod is a modification time rather than
    # a publication time, so claiming it as posted_date would be wrong.
    assert all(j.location is None for j in synopsys_jobs)
    assert all(j.posted_date is None for j in synopsys_jobs)


def test_a_portal_on_its_own_domain_parses_the_same_way(ea_jobs):
    # EA runs Avature on jobs.ea.com rather than on avature.net, which is why
    # BOARDS holds a whole sitemap URL rather than a tenant name.
    assert len(ea_jobs) == 361
    assert all(j.url.startswith("https://jobs.ea.com/en_US/careers/JobDetail/") for j in ea_jobs)
    assert all(j.company == "Electronic Arts" for j in ea_jobs)


def test_ea_titles_keep_every_word_because_its_slugs_omit_the_id(ea_jobs):
    # Unlike Synopsys, EA does not repeat the id in the slug, so nothing should
    # be stripped from these titles.
    assert not any(j.title.endswith(j.job_id) for j in ea_jobs)
    assert all(j.title for j in ea_jobs)


def test_every_board_becomes_a_static_scraper():
    built = scrapers()
    assert len(built) == len(BOARDS)
    assert all(s.config.fetch_mode is FetchMode.STATIC for s in built)
    assert {s.config.name for s in built} == set(BOARDS)


def test_every_board_url_is_a_sitemap():
    assert all(url.endswith("sitemap.xml") for url in BOARDS.values())
