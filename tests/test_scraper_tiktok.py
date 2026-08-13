import json
from pathlib import Path

import pytest

from jobwatch.fetch import split_post_url
from jobwatch.models import FetchMode
from jobwatch.scrapers.bytedance import PAGE_SIZE, ByteDanceScraper
from jobwatch.scrapers.tiktok import REQUEST_HEADERS, TikTokScraper

FIXTURE = Path(__file__).parent / "fixtures" / "tiktok_jobs.json"


@pytest.fixture(scope="module")
def tiktok_jobs():
    return TikTokScraper().parse(FIXTURE.read_text(encoding="utf-8"))


def test_parses_a_full_page(tiktok_jobs):
    assert len(tiktok_jobs) == PAGE_SIZE
    assert len({j.job_id for j in tiktok_jobs}) == PAGE_SIZE


def test_jobs_are_attributed_to_tiktok_not_bytedance(tiktok_jobs):
    assert {j.company for j in tiktok_jobs} == {"TikTok"}


def test_job_url_points_at_the_public_posting(tiktok_jobs):
    for job in tiktok_jobs[:20]:
        assert job.url == f"https://lifeattiktok.com/search/{job.job_id}"


def test_every_posting_has_a_location(tiktok_jobs):
    assert all(j.location for j in tiktok_jobs)


def test_site_path_header_is_sent():
    # Without it the endpoint answers a bare `invalid request`, and ByteDance's
    # own value is rejected here — the header names the site, not a language.
    assert REQUEST_HEADERS == {"website-path": "tiktok"}
    assert TikTokScraper.config.request_headers == REQUEST_HEADERS
    assert REQUEST_HEADERS != ByteDanceScraper.config.request_headers


def test_reads_a_different_host_from_bytedance():
    endpoint, _ = split_post_url(TikTokScraper.config.career_url)
    assert endpoint.startswith("https://lifeattiktok.com/")
    other, _ = split_post_url(ByteDanceScraper.config.career_url)
    assert endpoint != other


def test_request_body_carries_the_required_empty_lists():
    # Shared with ByteDance's builder; the endpoint 400s if these are absent.
    _, body = split_post_url(TikTokScraper.config.career_url)
    for key in ("recruitment_id_list", "job_category_id_list",
                "subject_id_list", "location_code_list"):
        assert body[key] == []
    assert body["offset"] == 0
    assert body["limit"] == PAGE_SIZE


def test_board_exposes_no_posting_date(tiktok_jobs):
    # publish_time is present on every record but null on all of them.
    assert all(j.posted_date is None for j in tiktok_jobs)


def test_board_is_read_in_full_because_recency_cannot_be_confirmed():
    assert TikTokScraper.config.paginate_fully is True


def test_page_ceiling_covers_the_whole_board(tiktok_jobs):
    # ~3,970 postings at 200 a page. A ceiling below that would truncate the
    # seed, which the engine refuses to persist.
    count = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]["count"]
    assert TikTokScraper.config.max_pages >= -(-count // PAGE_SIZE)


def test_records_missing_required_fields_are_skipped():
    payload = json.dumps({"data": {"job_post_list": [
        {"id": "1", "title": "Kept"},
        {"id": "2"},
        {"title": "No id"},
        "not-a-dict",
    ]}})
    assert [j.job_id for j in TikTokScraper().parse(payload)] == ["1"]


def test_empty_board_parses_to_no_jobs():
    assert TikTokScraper().parse(json.dumps({"data": {"job_post_list": []}})) == []


def test_a_short_page_ends_pagination():
    scraper = TikTokScraper()
    payload = json.dumps({"data": {"job_post_list": [{"id": "1", "title": "x"}], "count": 1}})
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_pagination_stops_once_the_count_is_reached():
    scraper = TikTokScraper()
    payload = json.dumps({"data": {
        "job_post_list": [{"id": str(i), "title": "x"} for i in range(PAGE_SIZE)],
        "count": PAGE_SIZE}})
    assert scraper.next_page_url(payload, scraper.config.career_url) is None


def test_pagination_advances_the_offset_on_the_tiktok_host():
    scraper = TikTokScraper()
    payload = json.dumps({"data": {
        "job_post_list": [{"id": str(i), "title": "x"} for i in range(PAGE_SIZE)],
        "count": PAGE_SIZE * 4}})
    nxt = scraper.next_page_url(payload, scraper.config.career_url)
    endpoint, body = split_post_url(nxt)
    assert body["offset"] == PAGE_SIZE
    assert endpoint.startswith("https://lifeattiktok.com/")


def test_scraper_uses_post_mode():
    assert TikTokScraper.config.fetch_mode is FetchMode.JSON_POST
