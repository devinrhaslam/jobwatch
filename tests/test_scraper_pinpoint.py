import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.pinpoint import BOARDS, PinpointScraper, scrapers

FIXTURE = Path(__file__).parent / "fixtures" / "pinpoint_impulse_postings.json"


def scraper() -> PinpointScraper:
    return PinpointScraper("Impulse Space", "impulsespace")


def record(**overrides):
    base = {
        "id": "290785",
        "title": "Senior Development Test Engineer",
        "url": "https://impulsespace.pinpointhq.com/en/postings/3ab1fb8a-6f79-4e03-87c3-9dbfba1b1f07",
        "location": {"city": "Redondo Beach", "province": "California", "name": "Redondo Beach "},
    }
    base.update(overrides)
    return base


def payload(*records):
    return json.dumps({"data": list(records)})


@pytest.fixture(scope="module")
def impulse_jobs():
    return scraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(impulse_jobs):
    assert len(impulse_jobs) == 40
    assert len({j.job_id for j in impulse_jobs}) == 40


def test_url_is_the_boards_own_posting_page(impulse_jobs):
    assert all(j.url.startswith("https://impulsespace.pinpointhq.com/") for j in impulse_jobs)
    assert all("/postings/" in j.url for j in impulse_jobs)


def test_location_is_assembled_rather_than_taken_from_the_padded_name():
    # `name` arrives as "Redondo Beach " and omits the province.
    (job,) = scraper().parse(payload(record()))
    assert job.location == "Redondo Beach, California"


def test_a_repeated_part_is_listed_once():
    (job,) = scraper().parse(
        payload(record(location={"city": "Mojave", "province": "Mojave"}))
    )
    assert job.location == "Mojave"


def test_the_display_name_is_the_fallback():
    (job,) = scraper().parse(payload(record(location={"name": "  Remote  "})))
    assert job.location == "Remote"


def test_a_posting_with_no_location_has_none():
    (job,) = scraper().parse(payload(record(location=None)))
    assert job.location is None


def test_records_missing_an_id_title_or_url_are_skipped():
    jobs = scraper().parse(
        payload(record(id=None), record(id="2", title=None),
                record(id="3", url=None), record(id="4"))
    )
    assert [j.job_id for j in jobs] == ["4"]


def test_no_posted_date_is_claimed(impulse_jobs):
    # The feed has no publication field at all — published_at is absent from
    # every record — so recency comes from snapshot diffing.
    assert all(j.posted_date is None for j in impulse_jobs)


def test_an_empty_board_parses_to_no_jobs():
    assert scraper().parse(json.dumps({"data": []})) == []


def test_every_board_becomes_a_static_scraper():
    built = scrapers()
    assert len(built) == len(BOARDS)
    assert all(s.config.fetch_mode is FetchMode.STATIC for s in built)
    assert all(s.config.career_url.endswith("/postings.json") for s in built)
    assert {s.config.name for s in built} == set(BOARDS)
