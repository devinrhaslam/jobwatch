import pytest

from jobwatch.registry import SCRAPERS, check_snapshot_path_collisions, get_scraper


def test_all_four_pilot_companies_registered():
    assert set(SCRAPERS) == {"Anthropic", "Stripe", "Cloudflare", "Meta"}


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
