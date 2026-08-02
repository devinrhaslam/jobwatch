from pathlib import Path

from jobwatch.scrapers.stripe import StripeScraper

FIXTURE = Path(__file__).parent / "fixtures" / "stripe_jobs_search.html"


def test_parses_all_jobs_from_embedded_json():
    jobs = StripeScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(jobs) == 513


def test_parses_known_job_fields():
    jobs = StripeScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    job = next(j for j in jobs if j.job_id == "8044460")
    assert job.title == "AI Engineer"
    assert job.url == "https://stripe.com/careers/listing/ai-engineer/8044460"
