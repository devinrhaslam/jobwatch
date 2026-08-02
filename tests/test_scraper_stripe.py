import json
from pathlib import Path

from jobwatch.scrapers.stripe import StripeScraper

FIXTURE = Path(__file__).parent / "fixtures" / "stripe_jobs_search.html"


def _synthetic_payload(listings: list[dict], locations: list[dict]) -> str:
    return json.dumps(
        {"listings": listings, "locations": locations},
        separators=(",", ":"),
    )


def test_negative_location_index_does_not_pick_up_unrelated_location():
    payload = _synthetic_payload(
        listings=[
            {
                "greenhouseId": 1,
                "title": "Engineer",
                "slug": "engineer",
                "locationIndices": [-1],
            }
        ],
        locations=[{"name": "San Francisco"}, {"name": "New York"}],
    )
    jobs = StripeScraper().parse(payload)
    assert len(jobs) == 1
    assert jobs[0].location is None


def test_out_of_range_location_index_is_skipped():
    payload = _synthetic_payload(
        listings=[
            {
                "greenhouseId": 2,
                "title": "Designer",
                "slug": "designer",
                "locationIndices": [99],
            }
        ],
        locations=[{"name": "San Francisco"}],
    )
    jobs = StripeScraper().parse(payload)
    assert len(jobs) == 1
    assert jobs[0].location is None


def test_location_entry_missing_name_does_not_raise():
    payload = _synthetic_payload(
        listings=[
            {
                "greenhouseId": 3,
                "title": "PM",
                "slug": "pm",
                "locationIndices": [0],
            }
        ],
        locations=[{"id": "loc-1"}],
    )
    jobs = StripeScraper().parse(payload)
    assert len(jobs) == 1
    assert jobs[0].location is None


def test_parses_all_jobs_from_embedded_json():
    jobs = StripeScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(jobs) == 513


def test_parses_known_job_fields():
    jobs = StripeScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    job = next(j for j in jobs if j.job_id == "8044460")
    assert job.title == "AI Engineer"
    assert job.url == "https://stripe.com/careers/listing/ai-engineer/8044460"
