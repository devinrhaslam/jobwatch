import pytest

from jobwatch.registry import SCRAPERS, check_snapshot_path_collisions, get_scraper
from jobwatch.scrapers.greenhouse import BOARDS


def test_every_greenhouse_board_is_registered():
    assert set(BOARDS) <= set(SCRAPERS)


def test_registry_is_exactly_the_greenhouse_boards_plus_meta():
    assert set(SCRAPERS) == set(BOARDS) | {"Meta"}


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
