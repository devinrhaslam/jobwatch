from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper


class _MinimalScraper(Scraper):
    config = CompanyConfig(
        name="Acme", career_url="https://acme.example", fetch_mode=FetchMode.STATIC
    )

    def parse(self, payload: str) -> list[Job]:
        return []


def test_next_page_url_defaults_to_none():
    scraper = _MinimalScraper()
    assert scraper.next_page_url("", "https://acme.example") is None
