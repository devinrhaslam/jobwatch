from pathlib import Path

from jobwatch.scrapers.meta import MetaScraper

FIXTURE = Path(__file__).parent / "fixtures" / "meta_jobsearch_page1.html"


def test_parses_jobs_from_fixture():
    jobs = MetaScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(jobs) == 10
    assert all(j.job_id.isdigit() for j in jobs)


def test_next_page_url_increments_page_param():
    current = (
        "https://www.metacareers.com/jobsearch/"
        "?sort_by_new=true&teams[0]=Software+Engineering&page=1"
    )
    next_url = MetaScraper().next_page_url("<html></html>", current)
    assert "page=2" in next_url
    assert "teams[0]" in next_url


def test_next_page_url_returns_none_past_max_pages():
    current = "https://www.metacareers.com/jobsearch/?page=15"
    assert MetaScraper().next_page_url("<html></html>", current) is None
