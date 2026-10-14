import json
from pathlib import Path

import pytest

from jobwatch.fetch import split_post_url
from jobwatch.models import FetchMode
from jobwatch.scrapers.hudsonrivertrading import HudsonRiverTradingScraper

FIXTURE = Path(__file__).parent / "fixtures" / "hrt_jobs.json"


@pytest.fixture(scope="module")
def hrt_jobs():
    return HudsonRiverTradingScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_the_whole_board_in_one_request(hrt_jobs):
    assert len(hrt_jobs) == 72
    assert len({j.job_id for j in hrt_jobs}) == 72


def test_job_id_is_the_wordpress_post_id_not_the_card_job_id(hrt_jobs):
    # data-jobid repeats across locations (53 distinct across 72 postings), so
    # keying on it would collapse real listings.
    assert all(j.job_id.isdigit() for j in hrt_jobs)
    assert len({j.job_id for j in hrt_jobs}) == len(hrt_jobs)


def test_job_url_is_the_public_posting(hrt_jobs):
    assert all(j.url.startswith("https://www.hudsonrivertrading.com/hrt-job/") for j in hrt_jobs)


def test_every_posting_has_a_location(hrt_jobs):
    assert all(j.location for j in hrt_jobs)


def test_multi_location_postings_are_joined():
    job = next(j for j in _parse_fixture() if "," in (j.location or ""))
    assert ", " in job.location


def _parse_fixture():
    return HudsonRiverTradingScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_location_excludes_the_bullet_separator(hrt_jobs):
    assert all("•" not in (j.location or "") for j in hrt_jobs)


def test_board_exposes_no_posting_date(hrt_jobs):
    assert all(j.posted_date is None for j in hrt_jobs)


def test_request_carries_the_plugin_render_settings():
    # The handler 500s without `setting`.
    _, body = split_post_url(HudsonRiverTradingScraper.config.career_url)
    assert body["action"] == "get_hrt_jobs_handler"
    assert "meta_data" in body["setting"]


def test_form_encoding_is_used():
    # The endpoint answers 400 to a JSON body.
    assert HudsonRiverTradingScraper.config.fetch_mode is FetchMode.FORM_POST


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps([
        {"ID": 1, "title": "Kept",
         "content": '<div class="hrt-card-item"><a class="hrt-card-title" href="https://x/1">Kept</a></div>'},
        {"ID": 2, "title": "No anchor", "content": "<div></div>"},
        {"title": "No id", "content": '<a class="hrt-card-title" href="https://x/3">x</a>'},
        "not-a-dict",
    ])
    assert [j.job_id for j in HudsonRiverTradingScraper().parse(payload)] == ["1"]


def test_titles_arrive_entity_encoded_and_are_decoded():
    payload = json.dumps([
        {"ID": 1, "title": "Algorithm Development (Quant Research &amp; Trading) Intern &#8211; 2027",
         "content": '<div class="hrt-card-item"><a class="hrt-card-title" href="https://x/1">x</a></div>'},
    ])
    [job] = HudsonRiverTradingScraper().parse(payload)
    assert job.title == "Algorithm Development (Quant Research & Trading) Intern \u2013 2027"


def test_empty_board_parses_to_no_jobs():
    assert HudsonRiverTradingScraper().parse("[]") == []


def test_unexpected_payload_shape_parses_to_no_jobs():
    assert HudsonRiverTradingScraper().parse('{"error":"x"}') == []


def test_single_request_means_no_pagination():
    scraper = HudsonRiverTradingScraper()
    assert scraper.next_page_url("[]", scraper.config.career_url) is None
