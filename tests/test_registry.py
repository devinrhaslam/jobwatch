import pytest

from jobwatch.registry import SCRAPERS, check_snapshot_path_collisions, get_scraper
from jobwatch.scrapers.ashby import BOARDS as ASHBY_BOARDS
from jobwatch.scrapers.eightfold import BOARDS as EIGHTFOLD_BOARDS
from jobwatch.scrapers.greenhouse import BOARDS as GREENHOUSE_BOARDS
from jobwatch.scrapers.smartrecruiters import BOARDS as SMARTRECRUITERS_BOARDS
from jobwatch.scrapers.workday import BOARDS as WORKDAY_BOARDS


_PLATFORMS = (
    GREENHOUSE_BOARDS,
    ASHBY_BOARDS,
    WORKDAY_BOARDS,
    EIGHTFOLD_BOARDS,
    SMARTRECRUITERS_BOARDS,
)
# Companies with a bespoke portal rather than a shared platform board.
_CUSTOM = {"Amazon", "Apple", "GitHub", "Google", "Snap", "Uber", "Meta"}


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
