from __future__ import annotations

from abc import ABC, abstractmethod

from jobwatch.models import CompanyConfig, Job


class Scraper(ABC):
    config: CompanyConfig

    @abstractmethod
    def parse(self, payload: str) -> list[Job]:
        ...

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        return None

    def detail_url(self, job: Job) -> str | None:
        """URL of a page carrying fuller data for this job, or None to skip.

        For boards whose listing is a stable public contract that happens to be
        thin — a sitemap with no titles — while each posting's own page is
        richly structured. The engine fetches this only for jobs it is about to
        report, so the cost is one request per genuinely new posting rather than
        one per posting on the board.
        """
        return None

    def parse_detail(self, payload: str, job: Job) -> Job:
        """Return `job` enriched from the page at `detail_url(job)`.

        Only called when detail_url returned a URL and the fetch succeeded. A
        scraper that cannot make sense of the payload should return `job`
        unchanged rather than raise; the engine treats a raise as a failed
        enrichment and keeps the unenriched job either way.
        """
        return job
