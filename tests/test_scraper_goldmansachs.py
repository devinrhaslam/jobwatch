import json

from jobwatch.fetch import split_post_url
from jobwatch.models import FetchMode
from jobwatch.scrapers.goldmansachs import (
    EXPERIENCES,
    PAGE_SIZE,
    GoldmanSachsScraper,
    _page_url,
)


def _payload(records, total=None):
    return json.dumps(
        {"data": {"roleSearch": {"totalCount": total or len(records), "items": records}}}
    )


def _role(**overrides):
    record = {
        "roleId": "180593_GS_MID_CAREER",
        "jobTitle": "Software Engineer - Data Platform",
        "lastPostedDate": "2026-08-03T15:54:43.011Z",
        "locations": [{"city": "Warsaw", "state": "Mazowieckie", "country": "Poland"}],
    }
    record.update(overrides)
    return record


def test_parses_a_role():
    job = GoldmanSachsScraper().parse(_payload([_role()]))[0]
    assert job.company == "Goldman Sachs"
    assert job.job_id == "180593_GS_MID_CAREER"
    assert job.title == "Software Engineer - Data Platform"
    assert job.location == "Warsaw, Mazowieckie, Poland"
    assert job.posted_date == "2026-08-03"


def test_url_uses_the_numeric_part_of_the_role_id():
    # roleId is "180593_GS_MID_CAREER" but the posting page is /roles/180593;
    # passing the whole id through would produce a board of dead links.
    job = GoldmanSachsScraper().parse(_payload([_role()]))[0]
    assert job.url == "https://higher.gs.com/roles/180593"


def test_job_id_keeps_the_full_role_id():
    # The suffix distinguishes otherwise-identical numbers across experience
    # streams, so the snapshot key keeps it even though the URL does not.
    job = GoldmanSachsScraper().parse(_payload([_role()]))[0]
    assert job.job_id.endswith("_GS_MID_CAREER")


def test_role_id_without_a_leading_number_is_skipped():
    payload = _payload([_role(roleId="GS_MID_CAREER"), _role()])
    assert [j.job_id for j in GoldmanSachsScraper().parse(payload)] == [
        "180593_GS_MID_CAREER"
    ]


def test_multiple_locations_are_all_reported():
    payload = _payload(
        [
            _role(
                locations=[
                    {"city": "London", "state": "England", "country": "United Kingdom"},
                    {"city": "New York", "state": "NY", "country": "United States"},
                ]
            )
        ]
    )
    job = GoldmanSachsScraper().parse(payload)[0]
    assert job.location == (
        "London, England, United Kingdom | New York, NY, United States"
    )


def test_partial_location_fields_are_tolerated():
    payload = _payload([_role(locations=[{"country": "Japan"}])])
    assert GoldmanSachsScraper().parse(payload)[0].location == "Japan"


def test_missing_locations_report_none():
    assert GoldmanSachsScraper().parse(_payload([_role(locations=[])]))[0].location is None


def test_records_without_id_or_title_are_skipped():
    payload = _payload([_role(jobTitle=None), _role(roleId=None), _role()])
    assert len(GoldmanSachsScraper().parse(payload)) == 1


def test_error_response_yields_no_jobs():
    assert GoldmanSachsScraper().parse(json.dumps({"errors": [{"message": "x"}]})) == []


def test_a_full_page_asks_for_the_next_one():
    payload = _payload([_role() for _ in range(PAGE_SIZE)], total=1096)
    nxt = GoldmanSachsScraper().next_page_url(payload, _page_url(1))
    _, body = split_post_url(nxt)
    assert body["variables"]["searchQueryInput"]["page"]["pageNumber"] == 2


def test_a_short_page_ends_pagination_even_though_total_says_otherwise():
    # The live board reports totalCount 1096 but stops yielding at 896, so the
    # short page — not the total — has to be what terminates the walk.
    payload = _payload([_role() for _ in range(96)], total=1096)
    assert GoldmanSachsScraper().next_page_url(payload, _page_url(5)) is None


def test_config_requests_external_roles_newest_first():
    config = GoldmanSachsScraper().config
    assert config.name == "Goldman Sachs"
    assert config.fetch_mode is FetchMode.JSON_POST
    endpoint, body = split_post_url(config.career_url)
    assert endpoint == "https://api-higher.gs.com/gateway/api/v1/graphql"
    search = body["variables"]["searchQueryInput"]
    assert search["page"] == {"pageSize": PAGE_SIZE, "pageNumber": 1}
    assert search["sort"] == {"sortStrategy": "POSTED_DATE", "sortOrder": "DESC"}
    # Internal-only and student roles are deliberately excluded.
    assert search["experiences"] == EXPERIENCES
    assert "INTERNAL_MOBILITY" not in EXPERIENCES
    assert "CAMPUS" not in EXPERIENCES
