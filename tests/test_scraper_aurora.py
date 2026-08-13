import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.aurora import AuroraScraper

FIXTURE = Path(__file__).parent / "fixtures" / "aurora_jobs_index.json"


def record(**overrides):
    base = {
        "id": "0e448c03-efd3-449b-9bab-867cdec10c6e",
        "title": "Truck Operations Specialist",
        "locations": ["Aledo, TX"],
        "isRemote": False,
        "publishedDate": "2026-08-10",
        "updatedAt": "2026-08-10T09:00:00Z",
    }
    base.update(overrides)
    return base


def payload(*records):
    return json.dumps({"jobs": list(records)})


@pytest.fixture(scope="module")
def aurora_jobs():
    return AuroraScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_every_posting_in_the_fixture(aurora_jobs):
    assert len(aurora_jobs) == 71
    assert len({j.job_id for j in aurora_jobs}) == 71


def test_url_uses_the_id_in_the_path_not_the_apply_links_query():
    # applyLink is aurora.tech/careers?ashby_jid=<id>; the listing itself links
    # to /careers/<id>, which is the shape a reported link should have.
    (job,) = AuroraScraper().parse(payload(record()))
    assert job.url == "https://aurora.tech/careers/0e448c03-efd3-449b-9bab-867cdec10c6e"


def test_job_id_appears_in_the_url(aurora_jobs):
    assert all(j.url.endswith(j.job_id) for j in aurora_jobs)


def test_posted_date_comes_from_published_date(aurora_jobs):
    assert all(j.posted_date for j in aurora_jobs)
    assert all(len(j.posted_date) == 10 for j in aurora_jobs)


def test_posted_dates_span_months_rather_than_one_moment(aurora_jobs):
    # Only a handful of distinct values, which looks fabricated until you see
    # they span months instead of clustering at the fetch: Aurora posts in
    # batches. This asserts the span, which a crawl timestamp cannot fake.
    dates = {j.posted_date for j in aurora_jobs}
    assert len(dates) > 1
    assert min(dates)[:7] != max(dates)[:7]


def test_location_lists_every_place():
    (job,) = AuroraScraper().parse(payload(record(locations=["Pittsburgh, PA", "Dallas, TX"])))
    assert job.location == "Pittsburgh, PA, Dallas, TX"


def test_a_remote_posting_is_marked():
    (job,) = AuroraScraper().parse(payload(record(locations=["Dallas, TX"], isRemote=True)))
    assert job.location == "Dallas, TX (Remote)"


def test_a_remote_posting_with_no_place_is_just_remote():
    (job,) = AuroraScraper().parse(payload(record(locations=[], isRemote=True)))
    assert job.location == "Remote"


def test_a_posting_with_no_place_has_no_location():
    (job,) = AuroraScraper().parse(payload(record(locations=None)))
    assert job.location is None


def test_records_missing_an_id_or_title_are_skipped():
    jobs = AuroraScraper().parse(
        payload(record(id=None), record(id="2", title=None), record(id="3"))
    )
    assert [j.job_id for j in jobs] == ["3"]


def test_an_empty_index_parses_to_no_jobs():
    assert AuroraScraper().parse(json.dumps({"jobs": []})) == []


def test_config_reads_the_index_over_plain_http():
    config = AuroraScraper().config
    assert config.name == "Aurora"
    assert config.fetch_mode is FetchMode.STATIC
    assert config.career_url == "https://aurora.tech/api/jobs-index"
