from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from jobwatch.scrapers.ashby import scrapers as ashby_scrapers
from jobwatch.scrapers.base import Scraper
from jobwatch.scrapers.greenhouse import scrapers as greenhouse_scrapers
from jobwatch.scrapers.meta import MetaScraper
from jobwatch.scrapers.workday import scrapers as workday_scrapers
from jobwatch.state import DEFAULT_STATE_DIR, snapshot_path


def check_snapshot_path_collisions(
    names: Iterable[str], state_dir: Path = DEFAULT_STATE_DIR
) -> None:
    by_path: dict[Path, list[str]] = {}
    for name in names:
        by_path.setdefault(snapshot_path(name, state_dir=state_dir), []).append(name)
    for path, colliding in by_path.items():
        if len(colliding) > 1:
            company_list = ", ".join(repr(name) for name in sorted(colliding))
            raise ValueError(
                f"snapshot filename collision: companies {company_list} "
                f"all map to {path.name!r}"
            )


_SCRAPER_INSTANCES = (
    *greenhouse_scrapers(),
    *ashby_scrapers(),
    *workday_scrapers(),
    MetaScraper(),  # custom portal, rejects plain HTTP — needs a headless browser
)

check_snapshot_path_collisions(scraper.config.name for scraper in _SCRAPER_INSTANCES)

SCRAPERS: dict[str, Scraper] = {
    scraper.config.name: scraper for scraper in _SCRAPER_INSTANCES
}


def get_scraper(name: str) -> Scraper:
    try:
        return SCRAPERS[name]
    except KeyError as exc:
        available = ", ".join(sorted(SCRAPERS))
        raise KeyError(f"unknown company {name!r}; available: {available}") from exc
