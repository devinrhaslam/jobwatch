import json
from pathlib import Path

import pytest

from jobwatch.models import FetchMode
from jobwatch.scrapers.greenhouse import BOARDS, GreenhouseScraper, scrapers

FIXTURE = Path(__file__).parent / "fixtures" / "greenhouse_cloudflare_jobs.json"


@pytest.fixture(scope="module")
def cloudflare_jobs():
    return GreenhouseScraper("Cloudflare", "cloudflare").parse(
        FIXTURE.read_text(encoding="utf-8")
    )


def test_parses_every_posting_in_the_fixture(cloudflare_jobs):
    assert len(cloudflare_jobs) == 286
    assert len({j.job_id for j in cloudflare_jobs}) == 286


def test_job_ids_match_the_ids_the_bespoke_scrapers_stored(cloudflare_jobs):
    # The retired page scrapers keyed on the Greenhouse id embedded in the job
    # URL, so migrating a company must not orphan its existing snapshot.
    job = next(j for j in cloudflare_jobs if j.job_id == "7902104")
    assert f"/jobs/{job.job_id}" in job.url


def test_parses_known_job_fields(cloudflare_jobs):
    job = next(j for j in cloudflare_jobs if j.job_id == "7902104")
    assert job.company == "Cloudflare"
    assert job.title
    assert job.url.startswith("https://")


def test_posted_date_is_populated_from_first_published(cloudflare_jobs):
    dated = [j for j in cloudflare_jobs if j.posted_date]
    assert dated, "Greenhouse exposes first_published; posted_date should be set"
    assert all(len(j.posted_date) == 10 for j in dated)  # YYYY-MM-DD


def test_location_prefers_metadata_over_a_work_arrangement(cloudflare_jobs):
    # Cloudflare's location.name is "Hybrid"/"In-Office"/"Distributed"; the real
    # place lives in the "Job Posting Location" metadata field.
    arrangements = {"Hybrid", "In-Office", "Distributed", "Remote"}
    located = [j for j in cloudflare_jobs if j.location]
    assert located
    assert not {j.location for j in located} <= arrangements


def test_missing_value_metadata_does_not_blank_the_location():
    payload = json.dumps(
        {
            "jobs": [
                {
                    "id": 1,
                    "title": "Software Engineer",
                    "absolute_url": "https://example.com/1",
                    "location": {"name": "San Francisco, CA"},
                    "metadata": [{"name": "Location Type", "value": None}],
                }
            ]
        }
    )
    job = GreenhouseScraper("Acme", "acme").parse(payload)[0]
    assert job.location == "San Francisco, CA"


def test_list_valued_metadata_location_is_joined():
    payload = json.dumps(
        {
            "jobs": [
                {
                    "id": 1,
                    "title": "Software Engineer",
                    "absolute_url": "https://example.com/1",
                    "location": {"name": "Hybrid"},
                    "metadata": [
                        {"name": "Job Posting Location", "value": ["Austin, US", "Lisbon, PT"]}
                    ],
                }
            ]
        }
    )
    job = GreenhouseScraper("Acme", "acme").parse(payload)[0]
    assert job.location == "Austin, US, Lisbon, PT"


def test_updated_at_is_not_used_as_a_posting_date():
    # updated_at moves in bulk re-indexes, so trusting it would report every
    # stale listing as posted today.
    payload = json.dumps(
        {
            "jobs": [
                {
                    "id": 1,
                    "title": "Software Engineer",
                    "absolute_url": "https://example.com/1",
                    "updated_at": "2026-08-03T18:25:22-04:00",
                }
            ]
        }
    )
    assert GreenhouseScraper("Acme", "acme").parse(payload)[0].posted_date is None


def test_records_missing_required_fields_are_skipped():
    # Only id and title are required. absolute_url is not: every Greenhouse job
    # has a canonical posting URL derivable from the board slug and id, so a
    # record without one is still usable (see the URL tests below).
    payload = json.dumps(
        {
            "jobs": [
                {"id": 1, "title": "Kept", "absolute_url": "https://example.com/1"},
                {"id": 2, "title": "Kept without a company URL"},
                {"title": "No id", "absolute_url": "https://example.com/3"},
                {"id": 4, "absolute_url": "https://example.com/4"},
            ]
        }
    )
    jobs = GreenhouseScraper("Acme", "acme").parse(payload)
    assert [j.job_id for j in jobs] == ["1", "2"]


def test_empty_board_parses_to_no_jobs():
    assert GreenhouseScraper("Acme", "acme").parse(json.dumps({"jobs": []})) == []


def test_scraper_is_static_and_targets_the_board_api():
    scraper = GreenhouseScraper("Jane Street", "janestreet")
    assert scraper.config.fetch_mode is FetchMode.STATIC
    assert scraper.config.career_url.endswith("/boards/janestreet/jobs")


def test_every_board_yields_a_distinct_registered_scraper():
    built = scrapers()
    assert len(built) == len(BOARDS)
    assert {s.config.name for s in built} == set(BOARDS)
    assert len({s.config.career_url for s in built}) == len(BOARDS)


def test_company_url_is_kept_when_its_path_identifies_the_job():
    payload = json.dumps(
        {"jobs": [{"id": 7995199, "title": "SWE",
                   "absolute_url": "https://careers.airbnb.com/positions/7995199?gh_jid=7995199"}]}
    )
    job = GreenhouseScraper("Airbnb", "airbnb").parse(payload)[0]
    assert job.url == "https://careers.airbnb.com/positions/7995199?gh_jid=7995199"


def test_listing_page_url_is_replaced_with_the_canonical_posting():
    # Stripe points absolute_url at a search page with the id only in a query
    # param. Once the posting closes that silently renders the full listing,
    # which reads as "the link took me to the jobs page, not the job".
    payload = json.dumps(
        {"jobs": [{"id": 4921361, "title": "Backend Engineer",
                   "absolute_url": "https://stripe.com/jobs/search?gh_jid=4921361"}]}
    )
    job = GreenhouseScraper("Stripe", "stripe").parse(payload)[0]
    assert job.url == "https://job-boards.greenhouse.io/stripe/jobs/4921361"


def test_pinterest_style_listing_url_is_also_replaced():
    payload = json.dumps(
        {"jobs": [{"id": 4813946, "title": "SWE II",
                   "absolute_url": "https://www.pinterestcareers.com/jobs/?gh_jid=4813946"}]}
    )
    job = GreenhouseScraper("Pinterest", "pinterest").parse(payload)[0]
    assert job.url == "https://job-boards.greenhouse.io/pinterest/jobs/4813946"


def test_missing_absolute_url_falls_back_to_the_canonical_posting():
    payload = json.dumps({"jobs": [{"id": 42, "title": "SWE"}]})
    job = GreenhouseScraper("Acme", "acme").parse(payload)[0]
    assert job.url == "https://job-boards.greenhouse.io/acme/jobs/42"


def test_a_job_id_appearing_only_as_a_substring_does_not_count_as_identified():
    # "/positions/12345678" must not satisfy job id "1234".
    payload = json.dumps(
        {"jobs": [{"id": 1234, "title": "SWE",
                   "absolute_url": "https://careers.acme.com/positions/12345678"}]}
    )
    job = GreenhouseScraper("Acme", "acme").parse(payload)[0]
    assert job.url == "https://job-boards.greenhouse.io/acme/jobs/1234"
