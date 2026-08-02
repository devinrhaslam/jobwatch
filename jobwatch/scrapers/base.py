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
