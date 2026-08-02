from pathlib import Path

from jobwatch.scrapers.cloudflare import CloudflareScraper

FIXTURE = Path(__file__).parent / "fixtures" / "cloudflare_careers.html"


def test_deduplicates_jobs_rendered_twice():
    jobs = CloudflareScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(jobs) == 285
    assert len({j.job_id for j in jobs}) == 285


def test_parses_posted_date():
    jobs = CloudflareScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    job = next(j for j in jobs if j.job_id == "8099002")
    assert job.posted_date == "2026-07-31"
    assert job.location == "Sales - Chicago, US"


def test_protocol_relative_href_is_resolved_against_the_career_url():
    html = """
    <a href="//boards.greenhouse.io/cloudflare/jobs/12345?gh_jid=12345">
      <p>Software Engineer</p>
      <p>Remote</p>
    </a>
    """
    jobs = CloudflareScraper().parse(html)
    assert jobs[0].url == "https://boards.greenhouse.io/cloudflare/jobs/12345?gh_jid=12345"
