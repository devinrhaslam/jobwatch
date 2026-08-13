from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.radancy import BOARDS, TITLE_LOCATION, RadancyScraper, scrapers

# The live feed is ~4.7 MB, almost all of it the full job description inlined
# into every item. The scraper never reads <description>, so the fixture keeps
# the real feed byte for byte except for those bodies, which are replaced with
# a placeholder — 191 KB, and verified to parse to exactly the same jobs as the
# untrimmed response. test_description_with_embedded_html_is_tolerated covers
# the shape that was trimmed away.
INTUIT_FIXTURE = Path(__file__).parent / "fixtures" / "radancy_intuit_rss.xml"
DISNEY_FIXTURE = Path(__file__).parent / "fixtures" / "radancy_disney_rss.xml"


@pytest.fixture(scope="module")
def jobs():
    return RadancyScraper("Intuit", "https://jobs.intuit.com").parse(
        INTUIT_FIXTURE.read_text(encoding="utf-8")
    )


def test_parses_every_item_in_the_feed(jobs):
    assert len(jobs) == 388
    assert len({j.job_id for j in jobs}) == 388


def test_job_id_is_the_last_path_segment_of_the_link(jobs):
    assert all(j.job_id.isdigit() for j in jobs)
    assert all(j.url.endswith(f"/{j.job_id}") for j in jobs)


def test_location_is_split_out_of_the_title(jobs):
    # Feed titles are "Title - (City, State, Country)"; leaving that in place
    # would put the location into every reported job title.
    assert all(j.location for j in jobs)
    # No title still carries a trailing " - (...)" location suffix. Checked
    # this way rather than "no title ends with ')'", because 46 real titles end
    # in a qualifier of their own — "Staff Product Manager (Mid-Market)" — and
    # those are correct.
    assert not any(TITLE_LOCATION.match(j.title) for j in jobs)
    assert not any(j.location in j.title for j in jobs)
    job = next(j for j in jobs if j.job_id == "87369440704")
    assert job.title == (
        "Principal Product Designer, Business Intelligence for QuickBooks and Mid-Market"
    )
    assert job.location == "Mountain View, California, United States"


def test_posted_date_is_unset_because_pubdate_is_a_feed_artefact(jobs):
    # The feed's pubDate is a regeneration timestamp, not a posting date; see
    # the scraper docstring for the evidence.
    assert all(j.posted_date is None for j in jobs)


def test_title_containing_a_dash_splits_at_the_trailing_parenthetical():
    payload = _feed(
        title="Staff Software Engineer - Front End - (Mountain View, California)",
        link="https://jobs.intuit.com/job/mountain-view/x/27595/123",
    )
    job = RadancyScraper("Intuit", "https://jobs.intuit.com").parse(payload)[0]
    assert job.title == "Staff Software Engineer - Front End"
    assert job.location == "Mountain View, California"


def test_title_with_its_own_trailing_parenthetical_keeps_it():
    # 46 real titles end in a qualifier like "(Mid-Market)". Only the " - (...)"
    # location suffix should be stripped, not any trailing parenthesis.
    payload = _feed(
        title="Staff Product Manager (Mid-Market) - (Mountain View, California)",
        link="https://jobs.intuit.com/job/mv/spm/27595/321",
    )
    job = RadancyScraper("Intuit", "https://jobs.intuit.com").parse(payload)[0]
    assert job.title == "Staff Product Manager (Mid-Market)"
    assert job.location == "Mountain View, California"


def test_title_without_a_location_is_kept_whole():
    payload = _feed(
        title="Staff Software Engineer",
        link="https://jobs.intuit.com/job/x/y/27595/123",
    )
    job = RadancyScraper("Intuit", "https://jobs.intuit.com").parse(payload)[0]
    assert job.title == "Staff Software Engineer"
    assert job.location is None


def test_item_with_a_non_numeric_final_segment_is_skipped():
    payload = _feed(title="T - (X)", link="https://jobs.intuit.com/job/x/y/27595/apply")
    assert RadancyScraper("Intuit", "https://jobs.intuit.com").parse(payload) == []


def test_item_without_a_link_is_skipped():
    payload = _feed(title="T - (X)", link="")
    assert RadancyScraper("Intuit", "https://jobs.intuit.com").parse(payload) == []


def test_description_with_embedded_html_is_tolerated():
    # Real items inline a full HTML description inside CDATA. It must not be
    # able to terminate the item early or leak into any parsed field.
    description = "<p>Build <b>things</b></p><ul><li>a &amp; b</li></ul></item>"
    payload = _feed(
        title="Engineer - (Mountain View, California)",
        link="https://jobs.intuit.com/job/mv/eng/27595/999",
        description=description,
    )
    job = RadancyScraper("Intuit", "https://jobs.intuit.com").parse(payload)[0]
    assert job.job_id == "999"
    assert job.title == "Engineer"
    assert job.location == "Mountain View, California"


def test_empty_feed_yields_no_jobs():
    payload = '<?xml version="1.0" encoding="utf-8"?><rss><channel></channel></rss>'
    assert RadancyScraper("Intuit", "https://jobs.intuit.com").parse(payload) == []


def test_config_targets_the_rss_feed_over_plain_http():
    config = RadancyScraper("Intuit", "https://jobs.intuit.com").config
    assert config.name == "Intuit"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.career_url == "https://jobs.intuit.com/rss"
    # The search pages are disallowed by robots.txt; the feed must not be
    # quietly swapped back to them.
    assert "search-jobs" not in config.career_url


def _feed(*, title: str, link: str, description: str = "desc") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>'
        "<item>"
        f"<title><![CDATA[{title}]]></title>"
        f"<description><![CDATA[{description}]]></description>"
        f"<link>{link}</link>"
        "<pubDate>Sat, 11 Jul 2026 03:30:36 GMT</pubDate>"
        "</item></channel></rss>"
    )


@pytest.fixture(scope="module")
def disney_jobs():
    return RadancyScraper("Disney", "https://jobs.disneycareers.com").parse(
        DISNEY_FIXTURE.read_text(encoding="utf-8")
    )


def test_the_same_parser_reads_a_second_radancy_portal(disney_jobs):
    # Disney runs the identical platform; if the shared parser ever drifts
    # toward one portal's quirks, one of these two boards will break first.
    assert len(disney_jobs) == 766
    assert len({j.job_id for j in disney_jobs}) == 766
    assert all(j.location for j in disney_jobs)
    assert all(j.url.startswith("https://jobs.disneycareers.com/job/") for j in disney_jobs)


def test_scrapers_cover_every_configured_board():
    built = {s.config.name for s in scrapers()}
    assert built == set(BOARDS)
    assert built == {"Arm", "Disney", "Intuit"}


def test_every_board_reads_its_own_host_feed():
    for scraper in scrapers():
        assert scraper.config.career_url == f"{BOARDS[scraper.config.name]}/rss"
        assert scraper.config.fetch_mode is FetchMode.STATIC
