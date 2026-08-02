from pathlib import Path
from urllib.parse import parse_qs, urlparse

from jobwatch.scrapers.meta import MetaScraper

FIXTURE = Path(__file__).parent / "fixtures" / "meta_jobsearch_page1.html"


def _job_cards(count: int) -> str:
    return "".join(
        f'<a href="/profile/job_details/{index}"><h3>Role {index}</h3></a>'
        for index in range(count)
    )


def test_parses_jobs_from_fixture():
    jobs = MetaScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(jobs) == 10
    assert all(j.job_id.isdigit() for j in jobs)


def test_next_page_url_increments_page_param_for_full_page():
    current = (
        "https://www.metacareers.com/jobsearch/"
        "?sort_by_new=true&teams[0]=Software+Engineering&page=1"
    )
    next_url = MetaScraper().next_page_url(_job_cards(10), current)
    assert "page=2" in next_url
    assert "teams[0]" in next_url


def test_next_page_url_returns_none_for_partial_page():
    current = "https://www.metacareers.com/jobsearch/?page=1"
    assert MetaScraper().next_page_url(_job_cards(9), current) is None


def test_next_page_url_returns_none_past_max_pages():
    current = "https://www.metacareers.com/jobsearch/?page=15"
    assert MetaScraper().next_page_url(_job_cards(10), current) is None


def test_next_page_url_preserves_sort_by_new():
    current = (
        "https://www.metacareers.com/jobsearch/"
        "?sort_by_new=true&teams[0]=Software+Engineering&page=1"
    )
    next_url = MetaScraper().next_page_url(_job_cards(10), current)
    assert "sort_by_new=true" in next_url


def test_next_page_url_preserves_repeated_query_params():
    current = (
        "https://www.metacareers.com/jobsearch/"
        "?sort_by_new=true&teams[0]=Software+Engineering"
        "&teams[0]=Product+Management&page=1"
    )
    next_url = MetaScraper().next_page_url(_job_cards(10), current)
    query = parse_qs(urlparse(next_url).query)
    assert query["teams[0]"] == ["Software Engineering", "Product Management"]
    assert query["page"] == ["2"]


def test_fixture_jobs_have_non_empty_locations():
    jobs = MetaScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(jobs) == 10
    for job in jobs:
        assert job.location
        assert job.location != "New"
