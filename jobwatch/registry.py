from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from jobwatch.scrapers.amazon import AmazonScraper
from jobwatch.scrapers.apple import AppleScraper
from jobwatch.scrapers.ashby import scrapers as ashby_scrapers
from jobwatch.scrapers.atlassian import AtlassianScraper
from jobwatch.scrapers.aurora import AuroraScraper
from jobwatch.scrapers.avature import scrapers as avature_scrapers
from jobwatch.scrapers.base import Scraper
from jobwatch.scrapers.bloomberg import BloombergScraper
from jobwatch.scrapers.bytedance import ByteDanceScraper
from jobwatch.scrapers.clearcompany import scrapers as clearcompany_scrapers
from jobwatch.scrapers.comeet import scrapers as comeet_scrapers
from jobwatch.scrapers.deelboard import scrapers as deelboard_scrapers
from jobwatch.scrapers.dynatrace import DynatraceScraper
from jobwatch.scrapers.eightfold import scrapers as eightfold_scrapers
from jobwatch.scrapers.github import GitHubScraper
from jobwatch.scrapers.goldmansachs import GoldmanSachsScraper
from jobwatch.scrapers.google import GoogleDeepMindScraper, GoogleScraper
from jobwatch.scrapers.greenhouse import scrapers as greenhouse_scrapers
from jobwatch.scrapers.hudsonrivertrading import HudsonRiverTradingScraper
from jobwatch.scrapers.icims import scrapers as icims_scrapers
from jobwatch.scrapers.jibe import scrapers as jibe_scrapers
from jobwatch.scrapers.lever import scrapers as lever_scrapers
from jobwatch.scrapers.linkedin import LinkedInScraper
from jobwatch.scrapers.meta import MetaScraper
from jobwatch.scrapers.oracle import scrapers as oracle_scrapers
from jobwatch.scrapers.pcsx import scrapers as pcsx_scrapers
from jobwatch.scrapers.phenom import scrapers as phenom_scrapers
from jobwatch.scrapers.pinpoint import scrapers as pinpoint_scrapers
from jobwatch.scrapers.radancy import scrapers as radancy_scrapers
from jobwatch.scrapers.retool import RetoolScraper
from jobwatch.scrapers.rippling import RipplingScraper
from jobwatch.scrapers.revolut import RevolutScraper
from jobwatch.scrapers.rivian import RivianScraper
from jobwatch.scrapers.sentinelone import SentinelOneScraper
from jobwatch.scrapers.shopify import ShopifyScraper
from jobwatch.scrapers.smartrecruiters import scrapers as smartrecruiters_scrapers
from jobwatch.scrapers.snap import SnapScraper
from jobwatch.scrapers.tesla import TeslaScraper
from jobwatch.scrapers.tiktok import TikTokScraper
from jobwatch.scrapers.twosigma import TwoSigmaScraper
from jobwatch.scrapers.valve import ValveScraper
from jobwatch.scrapers.walmart import WalmartScraper
from jobwatch.scrapers.wayfair import WayfairScraper
from jobwatch.scrapers.workable import scrapers as workable_scrapers
from jobwatch.scrapers.workday import scrapers as workday_scrapers
from jobwatch.scrapers.zed import ZedScraper
from jobwatch.scrapers.zoom import ZoomScraper
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
    *lever_scrapers(),
    *workday_scrapers(),
    *eightfold_scrapers(),
    *smartrecruiters_scrapers(),
    *radancy_scrapers(),
    *pcsx_scrapers(),
    *oracle_scrapers(),
    *avature_scrapers(),
    *icims_scrapers(),
    *workable_scrapers(),
    *comeet_scrapers(),
    *clearcompany_scrapers(),
    *pinpoint_scrapers(),
    *phenom_scrapers(),
    *deelboard_scrapers(),
    *jibe_scrapers(),
    # Bespoke portals: each answers plain JSON, so none needs a browser.
    AmazonScraper(),
    AppleScraper(),
    AtlassianScraper(),
    AuroraScraper(),
    BloombergScraper(),
    ByteDanceScraper(),
    DynatraceScraper(),
    GitHubScraper(),
    GoldmanSachsScraper(),
    GoogleScraper(),
    GoogleDeepMindScraper(),
    HudsonRiverTradingScraper(),
    LinkedInScraper(),
    RetoolScraper(),
    RipplingScraper(),
    RivianScraper(),
    SentinelOneScraper(),
    ShopifyScraper(),
    TikTokScraper(),
    TwoSigmaScraper(),
    ValveScraper(),
    WalmartScraper(),
    WayfairScraper(),
    SnapScraper(),
    ZedScraper(),
    ZoomScraper(),
    RevolutScraper(),  # 403s to plain HTTP and to Chromium; Firefox is served
    MetaScraper(),  # custom portal, rejects plain HTTP — needs a headless browser
    TeslaScraper(),  # behind Akamai; needs headless Firefox, which it does serve
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
