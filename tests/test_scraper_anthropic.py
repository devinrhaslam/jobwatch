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


def test_does_not_depend_on_the_caption_class_name():
    # The design requires scrapers to key off structure/href, not class
    # names, since those change with redesigns. Any two <p> descendants
    # should work, regardless of their class.
    html = """
    <a href="https://job-boards.greenhouse.io/anthropic/jobs/99999">
      <p class="totally-different-class">Staff Engineer</p>
      <p class="totally-different-class">New York, NY</p>
    </a>
    """
    jobs = AnthropicScraper().parse(html)
    assert jobs[0].title == "Staff Engineer"
    assert jobs[0].location == "New York, NY"


def test_relative_href_is_resolved_against_the_career_url():
    html = """
    <a href="/anthropic/jobs/12345">
      <p class="caption">Software Engineer</p>
      <p class="caption">Remote</p>
    </a>
    """
    jobs = AnthropicScraper().parse(html)
    assert jobs[0].url == "https://www.anthropic.com/anthropic/jobs/12345"
