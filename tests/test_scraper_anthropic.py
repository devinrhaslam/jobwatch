from pathlib import Path

from jobwatch.scrapers.anthropic import AnthropicScraper

FIXTURE = Path(__file__).parent / "fixtures" / "anthropic_jobs.html"


def test_parses_all_jobs_from_fixture():
    jobs = AnthropicScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(jobs) == 400
    assert len({j.job_id for j in jobs}) == 400


def test_parses_known_job_fields():
    jobs = AnthropicScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    job = next(j for j in jobs if j.job_id == "4980436008")
    assert "Research Manager" in job.title
    assert job.location == "San Francisco, CA"
    assert job.url == "https://job-boards.greenhouse.io/anthropic/jobs/4980436008"
