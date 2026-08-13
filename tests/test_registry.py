import pytest

from jobwatch.registry import SCRAPERS, check_snapshot_path_collisions, get_scraper
from jobwatch.scrapers.ashby import BOARDS as ASHBY_BOARDS
from jobwatch.scrapers.ashby import GRAPHQL_BOARDS as ASHBY_GRAPHQL_BOARDS
from jobwatch.scrapers.avature import BOARDS as AVATURE_BOARDS
from jobwatch.scrapers.clearcompany import BOARDS as CLEARCOMPANY_BOARDS
from jobwatch.scrapers.comeet import BOARDS as COMEET_BOARDS
from jobwatch.scrapers.deelboard import BOARDS as DEELBOARD_BOARDS
from jobwatch.scrapers.eightfold import BOARDS as EIGHTFOLD_BOARDS
from jobwatch.scrapers.greenhouse import BOARDS as GREENHOUSE_BOARDS
from jobwatch.scrapers.icims import BOARDS as ICIMS_BOARDS
from jobwatch.scrapers.jibe import BOARDS as JIBE_BOARDS
from jobwatch.scrapers.lever import BOARDS as LEVER_BOARDS
from jobwatch.scrapers.oracle import BOARDS as ORACLE_BOARDS
from jobwatch.scrapers.pcsx import BOARDS as PCSX_BOARDS
from jobwatch.scrapers.phenom import BOARDS as PHENOM_BOARDS
from jobwatch.scrapers.pinpoint import BOARDS as PINPOINT_BOARDS
from jobwatch.scrapers.radancy import BOARDS as RADANCY_BOARDS
from jobwatch.scrapers.smartrecruiters import BOARDS as SMARTRECRUITERS_BOARDS
from jobwatch.scrapers.workable import BOARDS as WORKABLE_BOARDS
from jobwatch.scrapers.workday import BOARDS as WORKDAY_BOARDS


_PLATFORMS = (
    GREENHOUSE_BOARDS,
    ASHBY_BOARDS,
    ASHBY_GRAPHQL_BOARDS,
    LEVER_BOARDS,
    WORKDAY_BOARDS,
    EIGHTFOLD_BOARDS,
    SMARTRECRUITERS_BOARDS,
    RADANCY_BOARDS,
    PCSX_BOARDS,
    ORACLE_BOARDS,
    AVATURE_BOARDS,
    WORKABLE_BOARDS,
    ICIMS_BOARDS,
    COMEET_BOARDS,
    CLEARCOMPANY_BOARDS,
    PINPOINT_BOARDS,
    PHENOM_BOARDS,
    DEELBOARD_BOARDS,
    JIBE_BOARDS,
)
# Companies with a bespoke portal rather than a shared platform board.
_CUSTOM = {
    "Amazon", "Apple", "Atlassian", "Bloomberg", "ByteDance", "GitHub", "Goldman Sachs", "Google",
    "Google DeepMind", "Hudson River Trading", "Rippling", "Rivian", "Shopify", "Snap", "Two Sigma", "Meta",
    "Tesla", "TikTok", "LinkedIn", "Walmart Global Tech", "Retool", "SentinelOne", "Dynatrace", "Wayfair", "Aurora", "Zed", "Zoom", "Valve", "Revolut",
}


def test_every_platform_board_is_registered():
    for boards in _PLATFORMS:
        assert set(boards) <= set(SCRAPERS)


def test_registry_is_exactly_the_platform_boards_plus_meta():
    expected = set(_CUSTOM)
    for boards in _PLATFORMS:
        expected |= set(boards)
    assert set(SCRAPERS) == expected


def test_no_company_is_claimed_by_two_platforms():
    for i, first in enumerate(_PLATFORMS):
        for second in _PLATFORMS[i + 1 :]:
            assert not set(first) & set(second)


def test_originally_piloted_companies_survived_the_greenhouse_migration():
    # These had bespoke page scrapers and existing snapshots; losing them from
    # the registry would silently stop watching a company that already works.
    for name in ("Anthropic", "Stripe", "Cloudflare", "Meta"):
        assert name in SCRAPERS, name


def test_get_scraper_returns_matching_scraper():
    scraper = get_scraper("Stripe")
    assert scraper.config.name == "Stripe"


def test_get_scraper_raises_with_available_list_on_unknown_name():
    with pytest.raises(KeyError, match="Anthropic"):
        get_scraper("Nonexistent Co")


def test_check_snapshot_path_collisions_raises_for_colliding_names(tmp_path):
    with pytest.raises(ValueError) as exc_info:
        check_snapshot_path_collisions(
            ["Booking.com", "Booking com"],
            state_dir=tmp_path,
        )
    message = str(exc_info.value)
    assert "Booking.com" in message
    assert "Booking com" in message
    assert "booking_com.json" in message
