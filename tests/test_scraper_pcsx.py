import json

from jobwatch.scrapers.pcsx import BOARDS, PAGE_SIZE, PcsxScraper, scrapers

MICROSOFT = PcsxScraper('Microsoft', *BOARDS['Microsoft'])
PAYPAL = PcsxScraper('PayPal', *BOARDS['PayPal'])


def _payload(positions, count=None):
    return json.dumps(
        {
            "status": 200,
            "error": {"message": "", "body": ""},
            "data": {
                "positions": positions,
                "count": len(positions) if count is None else count,
            },
        }
    )


def _position(**overrides):
    record = {
        "id": 1970393556867431,
        "displayJobId": "200037751",
        "name": "Software Engineer II",
        "locations": ["Redmond, WA, United States"],
        "postedTs": 1785885560,
        "positionUrl": "/careers/job/1970393556867431",
    }
    record.update(overrides)
    return record


def test_parses_position_into_job():
    jobs = MICROSOFT.parse(_payload([_position()]))

    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "Microsoft"
    # The requisition number, not the portal's internal id: it survives a
    # re-index of the internal ids that the URL is built from.
    assert job.job_id == "200037751"
    assert job.title == "Software Engineer II"
    assert job.location == "Redmond, WA, United States"
    assert job.url == (
        "https://apply.careers.microsoft.com/careers/job/1970393556867431"
    )
    assert job.posted_date == "2026-08-04"


def test_joins_multiple_locations_without_repeating_them():
    jobs = MICROSOFT.parse(
        _payload([_position(locations=["Redmond, WA", "Remote", "Redmond, WA"])])
    )

    assert jobs[0].location == "Redmond, WA, Remote"


def test_falls_back_to_building_the_url_when_position_url_is_absent():
    jobs = MICROSOFT.parse(_payload([_position(positionUrl=None)]))

    assert jobs[0].url == (
        "https://apply.careers.microsoft.com/careers/job/1970393556867431"
    )


def test_falls_back_to_internal_id_when_the_requisition_is_absent():
    jobs = MICROSOFT.parse(_payload([_position(displayJobId=None)]))

    assert jobs[0].job_id == "1970393556867431"


def test_posted_date_is_none_when_the_timestamp_is_missing_or_junk():
    for bad in (None, 0, "not-a-timestamp"):
        jobs = MICROSOFT.parse(_payload([_position(postedTs=bad)]))
        assert jobs[0].posted_date is None, bad


def test_skips_records_missing_a_title():
    payload = _payload([_position(), _position(displayJobId="2", name=None)])

    assert [job.job_id for job in MICROSOFT.parse(payload)] == ["200037751"]


def test_next_page_advances_start_by_the_page_size():
    payload = _payload([_position(displayJobId=str(i)) for i in range(PAGE_SIZE)], count=100)

    nxt = MICROSOFT.next_page_url(payload, "https://x/api/pcsx/search?start=0")

    assert "start=10" in nxt


def test_next_page_is_none_on_a_short_page():
    payload = _payload([_position()], count=100)

    assert MICROSOFT.next_page_url(payload, "https://x?start=0") is None


def test_next_page_is_none_once_the_count_is_reached():
    payload = _payload([_position(displayJobId=str(i)) for i in range(PAGE_SIZE)], count=20)

    nxt = MICROSOFT.next_page_url(payload, "https://x?start=10")

    assert nxt is None


def test_pagination_ceiling_covers_the_whole_board():
    # 1,849 postings at 10 per page needs ~185 requests; a ceiling below that
    # would silently truncate the seed.
    assert MICROSOFT.config.max_pages >= 1849 / PAGE_SIZE


def test_the_same_parser_serves_a_second_pcsx_host():
    # PayPal runs PCSX on its own Eightfold host rather than Microsoft's apply
    # host. Posting URLs must be built against the board's own host, or every
    # PayPal link would point at microsoft.com.
    payload = _payload([_position(positionUrl="/careers/job/274921487587")])
    job = PAYPAL.parse(payload)[0]
    assert job.company == "PayPal"
    assert job.url == "https://paypal.eightfold.ai/careers/job/274921487587"


def test_each_board_pages_against_its_own_host():
    for scraper in scrapers():
        host = BOARDS[scraper.config.name][0]
        assert scraper.config.career_url.startswith(f"{host}/api/pcsx/search")
        payload = _payload([_position() for _ in range(PAGE_SIZE)], count=999)
        nxt = scraper.next_page_url(payload, scraper.config.career_url)
        assert nxt.startswith(f"{host}/api/pcsx/search")
        assert "start=10" in nxt


def test_scrapers_cover_every_configured_board():
    assert {s.config.name for s in scrapers()} == set(BOARDS)
    assert {s.config.name for s in scrapers()} == {"Microsoft", "PayPal", "Qualcomm"}
