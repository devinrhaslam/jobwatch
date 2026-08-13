import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.revolut import RevolutScraper

FIXTURE = Path(__file__).parent / "fixtures" / "revolut_careers.html"


def page(*positions):
    data = {"props": {"pageProps": {"positions": list(positions)}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def record(**overrides):
    base = {
        "id": "ba99036f-306a-4d82-98bc-8ff73853d41c",
        "text": "Graphic Designer (Growth)",
        "locations": [{"name": "Tokyo", "type": "office"}],
    }
    base.update(overrides)
    return base


@pytest.fixture(scope="module")
def revolut_jobs():
    return RevolutScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_the_whole_board_not_the_six_that_render(revolut_jobs):
    # The page shows six postings before "Show more"; the data holds them all.
    assert len(revolut_jobs) > 500
    assert len({j.job_id for j in revolut_jobs}) == len(revolut_jobs)


def test_url_is_rebuilt_from_the_title_and_id():
    # The record carries no slug, so the posting URL is reconstructed.
    (job,) = RevolutScraper().parse(page(record()))
    assert job.url == (
        "https://www.revolut.com/en-US/careers/position/"
        "graphic-designer-growth-ba99036f-306a-4d82-98bc-8ff73853d41c/"
    )


def test_punctuation_in_a_title_collapses_to_single_hyphens():
    (job,) = RevolutScraper().parse(page(record(text="Strategy & Operations Manager")))
    assert "/position/strategy-operations-manager-" in job.url


def test_every_office_is_listed():
    (job,) = RevolutScraper().parse(page(record(locations=[
        {"name": "Krakow", "type": "office"}, {"name": "Lisbon", "type": "office"}])))
    assert job.location == "Krakow, Lisbon"


def test_a_remote_posting_is_marked_once():
    # Several place names already say "Remote"; the marker must not double up.
    (job,) = RevolutScraper().parse(page(record(locations=[
        {"name": "Poland - Remote", "type": "remote"}])))
    assert job.location == "Poland - Remote"


def test_a_remote_posting_with_a_plain_office_name_is_marked():
    (job,) = RevolutScraper().parse(page(record(locations=[{"name": "Tokyo", "type": "remote"}])))
    assert job.location == "Tokyo (Remote)"


def test_a_posting_with_no_locations_has_none():
    (job,) = RevolutScraper().parse(page(record(locations=[])))
    assert job.location is None


def test_records_missing_an_id_or_title_are_skipped():
    jobs = RevolutScraper().parse(page(record(id=None), record(id="2", text=None), record(id="3")))
    assert [j.job_id for j in jobs] == ["3"]


def test_a_repeated_id_is_reported_once():
    assert len(RevolutScraper().parse(page(record(), record()))) == 1


def test_a_page_without_the_data_block_parses_to_no_jobs():
    assert RevolutScraper().parse("<html><body>security check</body></html>") == []


def test_unparseable_data_does_not_raise():
    assert RevolutScraper().parse('<script id="__NEXT_DATA__">not json</script>') == []


def test_no_posted_date_is_claimed(revolut_jobs):
    assert all(j.posted_date is None for j in revolut_jobs)


def test_config_renders_in_firefox_because_chromium_is_challenged():
    config = RevolutScraper().config
    assert config.name == "Revolut"
    assert config.fetch_mode is FetchMode.RENDERED
    assert config.browser_engine == "firefox"
    # A script tag is never visible, so readiness keys on a rendered link.
    assert "position" in config.wait_for_selector
