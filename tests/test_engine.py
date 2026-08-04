from jobwatch.engine import MAX_PAGES, MIN_JOBS_FOR_SUSPICIOUS_CHECK, run_company
from jobwatch.fetch import FetchBlocked, FetchError
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper
from jobwatch.state import load_snapshot, save_snapshot, snapshot_path


class FakeScraper(Scraper):
    """Pages are addressed by index; the fetch_page stub echoes/derives the
    index as the 'payload' so parse() and next_page_url() can stay pure."""

    def __init__(self, pages: list[list[Job]], config: CompanyConfig | None = None):
        self.config = config or CompanyConfig(
            name="Acme", career_url="0", fetch_mode=FetchMode.STATIC
        )
        self._pages = pages

    def parse(self, payload: str) -> list[Job]:
        return self._pages[int(payload)]

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        next_index = int(payload) + 1
        if next_index >= len(self._pages):
            return None
        return str(next_index)


class RaisingScraper(FakeScraper):
    """Like FakeScraper, but parse() raises for one specific page index,
    simulating a site markup change breaking a BeautifulSoup selector."""

    def __init__(self, pages, raise_at_index, config=None):
        super().__init__(pages, config)
        self._raise_at_index = raise_at_index

    def parse(self, payload: str) -> list[Job]:
        if int(payload) == self._raise_at_index:
            raise KeyError("missing expected field")
        return super().parse(payload)


def _job(job_id, title="Software Engineer"):
    return Job(
        company="Acme", job_id=job_id, title=title, url=f"https://acme.example/{job_id}"
    )


def test_first_run_seeds_without_reporting_new_jobs(tmp_path):
    scraper = FakeScraper([[_job("1"), _job("2")]])
    result = run_company(scraper, state_dir=tmp_path, fetch_page=lambda c, u: "0")
    assert result.status == "seeded"
    assert result.new_jobs == []
    assert result.total_jobs == 2


def test_zero_job_seed_run_fails_loudly_and_does_not_persist(tmp_path):
    result = run_company(
        FakeScraper([[]]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )

    assert result.status == "failed"
    assert "seed" in result.detail.lower()
    assert not snapshot_path("Acme", tmp_path).exists()


def test_seed_is_retried_after_a_failed_zero_job_seed(tmp_path):
    run_company(FakeScraper([[]]), state_dir=tmp_path, fetch_page=lambda c, u: "0")

    result = run_company(
        FakeScraper([[_job("1")]]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )

    assert result.status == "seeded"
    assert result.new_jobs == []
    assert result.total_jobs == 1


def test_unchanged_second_run_reports_no_new_jobs(tmp_path):
    scraper = FakeScraper([[_job("1"), _job("2")]])
    run_company(scraper, state_dir=tmp_path, fetch_page=lambda c, u: "0")
    result = run_company(scraper, state_dir=tmp_path, fetch_page=lambda c, u: "0")
    assert result.status == "ok"
    assert result.new_jobs == []


def test_genuinely_new_job_is_reported_once(tmp_path):
    run_company(
        FakeScraper([[_job("1")]]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    scraper_with_new_job = FakeScraper([[_job("1"), _job("2")]])
    result = run_company(
        scraper_with_new_job, state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    assert result.status == "ok"
    assert [j.job_id for j in result.new_jobs] == ["2"]

    result_again = run_company(
        scraper_with_new_job, state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    assert result_again.new_jobs == []


def test_departed_job_reappearing_is_not_reported_again(tmp_path):
    run_company(
        FakeScraper([[_job("1"), _job("2")]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: "0",
    )
    run_company(
        FakeScraper([[_job("1")]]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    result = run_company(
        FakeScraper([[_job("1"), _job("2")]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: "0",
    )
    assert result.new_jobs == []


def test_zero_jobs_against_nonempty_snapshot_fails_without_overwriting_state(tmp_path):
    run_company(
        FakeScraper([[_job("1"), _job("2")]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: "0",
    )
    result = run_company(
        FakeScraper([[]]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    assert result.status == "failed"
    assert set(load_snapshot("Acme", tmp_path)) == {"1", "2"}


def test_existing_empty_snapshot_with_zero_jobs_fails_not_silently_ok(tmp_path):
    # Simulates a scraper that seeded fine once (writing an empty snapshot for
    # a company with no jobs yet) and then broke before ever posting anything:
    # the snapshot file exists but is empty, so this is NOT a seed run.
    save_snapshot("Acme", {}, tmp_path)

    result = run_company(
        FakeScraper([[]]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )

    assert result.status == "failed"


def test_existing_empty_snapshot_with_real_jobs_reports_them_as_ok(tmp_path):
    save_snapshot("Acme", {}, tmp_path)

    result = run_company(
        FakeScraper([[_job("1"), _job("2")]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: "0",
    )

    assert result.status == "ok"
    assert {j.job_id for j in result.new_jobs} == {"1", "2"}


def test_pagination_stops_early_when_page_has_no_new_ids(tmp_path):
    run_company(
        FakeScraper([[_job("1")], [_job("2")]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: u,
    )
    calls = []

    def counting_fetch(config, url):
        calls.append(url)
        return url

    result = run_company(
        FakeScraper([[_job("1")], [_job("2")]]),
        state_dir=tmp_path,
        fetch_page=counting_fetch,
    )
    assert calls == ["0"]
    assert result.new_jobs == []


def test_pagination_stops_at_page_ceiling(tmp_path):
    class EndlessScraper(FakeScraper):
        def parse(self, payload):
            return [_job(payload)]

        def next_page_url(self, payload, current_url):
            return str(int(payload) + 1)

    calls = []

    def counting_fetch(config, url):
        calls.append(url)
        return url

    result = run_company(
        EndlessScraper([]), state_dir=tmp_path, fetch_page=counting_fetch
    )

    assert len(calls) == MAX_PAGES
    assert calls == [str(index) for index in range(MAX_PAGES)]
    assert result.total_jobs == MAX_PAGES
    assert result.detail is not None
    assert str(MAX_PAGES) in result.detail


def test_pagination_deduplicates_job_ids_across_pages(tmp_path):
    result = run_company(
        FakeScraper([[_job("1")], [_job("1")]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: u,
    )

    assert result.total_jobs == 1
    assert set(load_snapshot("Acme", tmp_path)) == {"1"}


def test_fetch_blocked_returns_blocked_status(tmp_path):
    def blocked_fetch(config, url):
        raise FetchBlocked("request blocked")

    result = run_company(
        FakeScraper([[_job("1")]]), state_dir=tmp_path, fetch_page=blocked_fetch
    )

    assert result.status == "blocked"


def test_fetch_error_returns_failed_status(tmp_path):
    def failed_fetch(config, url):
        raise FetchError("request failed")

    result = run_company(
        FakeScraper([[_job("1")]]), state_dir=tmp_path, fetch_page=failed_fetch
    )

    assert result.status == "failed"


def test_later_page_fetch_error_keeps_already_collected_jobs(tmp_path):
    def fetch_until_second_page(config, url):
        if url == "1":
            raise FetchError("request failed on second page")
        return url

    result = run_company(
        FakeScraper([[_job("1")], [_job("2")]]),
        state_dir=tmp_path,
        fetch_page=fetch_until_second_page,
    )

    assert result.status == "seeded"
    assert result.total_jobs == 1
    assert set(load_snapshot("Acme", tmp_path)) == {"1"}
    assert result.detail is not None


def test_first_page_parse_error_returns_failed_naming_the_parser(tmp_path):
    scraper = RaisingScraper([[_job("1")]], raise_at_index=0)

    result = run_company(scraper, state_dir=tmp_path, fetch_page=lambda c, u: "0")

    assert result.status == "failed"
    assert "parser" in result.detail.lower()
    assert "missing expected field" in result.detail


def test_later_page_parse_error_keeps_already_collected_jobs(tmp_path):
    scraper = RaisingScraper([[_job("1")], [_job("2")]], raise_at_index=1)

    result = run_company(scraper, state_dir=tmp_path, fetch_page=lambda c, u: u)

    assert result.status == "seeded"
    assert result.total_jobs == 1
    assert set(load_snapshot("Acme", tmp_path)) == {"1"}
    assert result.detail is not None


def test_dry_run_reports_results_without_persisting_snapshot(tmp_path):
    result = run_company(
        FakeScraper([[_job("1")]]),
        state_dir=tmp_path,
        dry_run=True,
        fetch_page=lambda c, u: "0",
    )

    assert result.status == "seeded"
    assert result.total_jobs == 1
    assert not snapshot_path("Acme", tmp_path).exists()


def test_suspicious_ratio_flags_likely_id_scheme_change(tmp_path):
    total = MIN_JOBS_FOR_SUSPICIOUS_CHECK
    run_company(
        FakeScraper([[_job(str(i)) for i in range(total)]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: "0",
    )
    new_count = int(total * 0.9)
    mostly_new_jobs = [_job(str(i)) for i in range(total - new_count)] + [
        _job(f"new-{i}") for i in range(new_count)
    ]
    result = run_company(
        FakeScraper([mostly_new_jobs]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    assert result.status == "suspicious"


def test_suspicious_ratio_does_not_fire_below_the_minimum_job_floor(tmp_path):
    # A small company (e.g. 4 roles) that turns over entirely is expected
    # churn, not a scheme change; below the floor the ratio check must not
    # trap it in "suspicious" forever (it never advances past the guard).
    run_company(
        FakeScraper([[_job("1"), _job("2"), _job("3"), _job("4")]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: "0",
    )
    all_new_jobs = [_job("new-1"), _job("new-2"), _job("new-3"), _job("new-4")]
    result = run_company(
        FakeScraper([all_new_jobs]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    assert result.status == "ok"
    assert {j.job_id for j in result.new_jobs} == {"new-1", "new-2", "new-3", "new-4"}


def test_paginate_fully_keeps_reading_past_a_page_of_known_jobs(tmp_path):
    """Boards not ordered by recency can hide a new posting behind pages of
    known ones. The default early stop would miss it."""
    config = CompanyConfig(
        name="Unsorted",
        career_url="0",
        fetch_mode=FetchMode.STATIC,
        paginate_fully=True,
    )
    pages = [[_job("1")], [_job("2")], [_job("late")]]
    run_company(
        FakeScraper([[_job("1")], [_job("2")]], config=config),
        state_dir=tmp_path,
        fetch_page=lambda c, u: u,
    )
    result = run_company(
        FakeScraper(pages, config=config), state_dir=tmp_path, fetch_page=lambda c, u: u
    )
    assert [j.job_id for j in result.new_jobs] == ["late"]


def test_early_stop_still_applies_when_paginate_fully_is_off(tmp_path):
    config = CompanyConfig(name="Sorted", career_url="0", fetch_mode=FetchMode.STATIC)
    pages = [[_job("1")], [_job("2")], [_job("late")]]
    run_company(
        FakeScraper([[_job("1")], [_job("2")]], config=config),
        state_dir=tmp_path,
        fetch_page=lambda c, u: u,
    )
    result = run_company(
        FakeScraper(pages, config=config), state_dir=tmp_path, fetch_page=lambda c, u: u
    )
    assert result.new_jobs == []


def test_pages_are_throttled_but_the_first_fetch_is_not_delayed(tmp_path):
    """Netflix reads 49 pages every run and a Workday seed ~196. Firing those
    back to back is impolite and was the likeliest source of the intermittent
    fetch failures that took a whole company down."""
    from jobwatch.engine import INTER_PAGE_DELAY_SECONDS, _fetch_all_pages

    config = CompanyConfig(name="Paged", career_url="0", fetch_mode=FetchMode.STATIC)
    scraper = FakeScraper([[_job("1")], [_job("2")], [_job("3")]], config=config)
    slept = []
    _fetch_all_pages(
        scraper,
        config,
        known_ids=None,
        fetch_page=lambda c, u: u,
        sleep=slept.append,
    )
    assert slept == [INTER_PAGE_DELAY_SECONDS] * 2  # three pages, two gaps


def test_a_single_page_company_is_never_delayed(tmp_path):
    from jobwatch.engine import _fetch_all_pages

    config = CompanyConfig(name="Single", career_url="0", fetch_mode=FetchMode.STATIC)
    slept = []
    _fetch_all_pages(
        FakeScraper([[_job("1")]], config=config),
        config,
        known_ids=None,
        fetch_page=lambda c, u: u,
        sleep=slept.append,
    )
    assert slept == []
