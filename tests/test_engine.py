from jobwatch.engine import MAX_PAGES, MIN_JOBS_FOR_SUSPICIOUS_CHECK, run_company
from jobwatch.fetch import FetchBlocked, FetchError
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper
from jobwatch.state import load_snapshot, save_snapshot, snapshot_path
from jobwatch.store import JsonSnapshotStore


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
    result = run_company(scraper, store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0")
    assert result.status == "seeded"
    assert result.new_jobs == []
    assert result.total_jobs == 2


def test_zero_job_seed_run_fails_loudly_and_does_not_persist(tmp_path):
    result = run_company(
        FakeScraper([[]]), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0"
    )

    assert result.status == "failed"
    assert "seed" in result.detail.lower()
    assert not snapshot_path("Acme", tmp_path).exists()


def test_seed_is_retried_after_a_failed_zero_job_seed(tmp_path):
    run_company(FakeScraper([[]]), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0")

    result = run_company(
        FakeScraper([[_job("1")]]), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0"
    )

    assert result.status == "seeded"
    assert result.new_jobs == []
    assert result.total_jobs == 1


def test_unchanged_second_run_reports_no_new_jobs(tmp_path):
    scraper = FakeScraper([[_job("1"), _job("2")]])
    run_company(scraper, store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0")
    result = run_company(scraper, store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0")
    assert result.status == "ok"
    assert result.new_jobs == []


def test_genuinely_new_job_is_reported_once(tmp_path):
    run_company(
        FakeScraper([[_job("1")]]), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0"
    )
    scraper_with_new_job = FakeScraper([[_job("1"), _job("2")]])
    result = run_company(
        scraper_with_new_job, store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0"
    )
    assert result.status == "ok"
    assert [j.job_id for j in result.new_jobs] == ["2"]

    result_again = run_company(
        scraper_with_new_job, store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0"
    )
    assert result_again.new_jobs == []


def test_departed_job_reappearing_is_not_reported_again(tmp_path):
    run_company(
        FakeScraper([[_job("1"), _job("2")]]),
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: "0",
    )
    run_company(
        FakeScraper([[_job("1")]]), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0"
    )
    result = run_company(
        FakeScraper([[_job("1"), _job("2")]]),
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: "0",
    )
    assert result.new_jobs == []


def test_zero_jobs_against_nonempty_snapshot_fails_without_overwriting_state(tmp_path):
    run_company(
        FakeScraper([[_job("1"), _job("2")]]),
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: "0",
    )
    result = run_company(
        FakeScraper([[]]), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0"
    )
    assert result.status == "failed"
    assert set(load_snapshot("Acme", tmp_path)) == {"1", "2"}


def test_existing_empty_snapshot_with_zero_jobs_fails_not_silently_ok(tmp_path):
    # Simulates a scraper that seeded fine once (writing an empty snapshot for
    # a company with no jobs yet) and then broke before ever posting anything:
    # the snapshot file exists but is empty, so this is NOT a seed run.
    save_snapshot("Acme", {}, tmp_path)

    result = run_company(
        FakeScraper([[]]), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0"
    )

    assert result.status == "failed"


def test_existing_empty_snapshot_with_real_jobs_reports_them_as_ok(tmp_path):
    save_snapshot("Acme", {}, tmp_path)

    result = run_company(
        FakeScraper([[_job("1"), _job("2")]]),
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: "0",
    )

    assert result.status == "ok"
    assert {j.job_id for j in result.new_jobs} == {"1", "2"}


def test_pagination_stops_early_when_page_has_no_new_ids(tmp_path):
    run_company(
        FakeScraper([[_job("1")], [_job("2")]]),
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: u,
    )
    calls = []

    def counting_fetch(config, url):
        calls.append(url)
        return url

    result = run_company(
        FakeScraper([[_job("1")], [_job("2")]]),
        store=JsonSnapshotStore(tmp_path),
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
        EndlessScraper([]), store=JsonSnapshotStore(tmp_path), fetch_page=counting_fetch
    )

    assert len(calls) == MAX_PAGES
    assert calls == [str(index) for index in range(MAX_PAGES)]
    assert result.total_jobs == MAX_PAGES
    assert result.detail is not None
    assert str(MAX_PAGES) in result.detail


def test_pagination_deduplicates_job_ids_across_pages(tmp_path):
    result = run_company(
        FakeScraper([[_job("1")], [_job("1")]]),
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: u,
    )

    assert result.total_jobs == 1
    assert set(load_snapshot("Acme", tmp_path)) == {"1"}


def test_fetch_blocked_returns_blocked_status(tmp_path):
    def blocked_fetch(config, url):
        raise FetchBlocked("request blocked")

    result = run_company(
        FakeScraper([[_job("1")]]), store=JsonSnapshotStore(tmp_path), fetch_page=blocked_fetch
    )

    assert result.status == "blocked"


def test_fetch_error_returns_failed_status(tmp_path):
    def failed_fetch(config, url):
        raise FetchError("request failed")

    result = run_company(
        FakeScraper([[_job("1")]]), store=JsonSnapshotStore(tmp_path), fetch_page=failed_fetch
    )

    assert result.status == "failed"


def test_later_page_fetch_error_keeps_already_collected_jobs(tmp_path):
    # Against an existing snapshot a short run is safe to keep: the pages it
    # did reach merge in, and the rest are picked up next run. (On a *seed*
    # run the same truncation is refused — see below.)
    save_snapshot("Acme", {"old": {"job_id": "old"}}, tmp_path)

    def fetch_until_second_page(config, url):
        if url == "1":
            raise FetchError("request failed on second page")
        return url

    result = run_company(
        FakeScraper([[_job("1")], [_job("2")]]),
        store=JsonSnapshotStore(tmp_path),
        fetch_page=fetch_until_second_page,
    )

    assert result.status == "ok"
    assert result.total_jobs == 1
    assert set(load_snapshot("Acme", tmp_path)) == {"old", "1"}
    assert result.detail is not None


def test_first_page_parse_error_returns_failed_naming_the_parser(tmp_path):
    scraper = RaisingScraper([[_job("1")]], raise_at_index=0)

    result = run_company(scraper, store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0")

    assert result.status == "failed"
    assert "parser" in result.detail.lower()
    assert "missing expected field" in result.detail


def test_later_page_parse_error_keeps_already_collected_jobs(tmp_path):
    save_snapshot("Acme", {"old": {"job_id": "old"}}, tmp_path)
    scraper = RaisingScraper([[_job("1")], [_job("2")]], raise_at_index=1)

    result = run_company(scraper, store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: u)

    assert result.status == "ok"
    assert result.total_jobs == 1
    assert set(load_snapshot("Acme", tmp_path)) == {"old", "1"}
    assert result.detail is not None


def test_dry_run_reports_results_without_persisting_snapshot(tmp_path):
    result = run_company(
        FakeScraper([[_job("1")]]),
        store=JsonSnapshotStore(tmp_path),
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
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: "0",
    )
    new_count = int(total * 0.9)
    mostly_new_jobs = [_job(str(i)) for i in range(total - new_count)] + [
        _job(f"new-{i}") for i in range(new_count)
    ]
    result = run_company(
        FakeScraper([mostly_new_jobs]), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0"
    )
    assert result.status == "suspicious"


def test_suspicious_ratio_does_not_fire_below_the_minimum_job_floor(tmp_path):
    # A small company (e.g. 4 roles) that turns over entirely is expected
    # churn, not a scheme change; below the floor the ratio check must not
    # trap it in "suspicious" forever (it never advances past the guard).
    run_company(
        FakeScraper([[_job("1"), _job("2"), _job("3"), _job("4")]]),
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: "0",
    )
    all_new_jobs = [_job("new-1"), _job("new-2"), _job("new-3"), _job("new-4")]
    result = run_company(
        FakeScraper([all_new_jobs]), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: "0"
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
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: u,
    )
    result = run_company(
        FakeScraper(pages, config=config), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: u
    )
    assert [j.job_id for j in result.new_jobs] == ["late"]


def test_early_stop_still_applies_when_paginate_fully_is_off(tmp_path):
    config = CompanyConfig(name="Sorted", career_url="0", fetch_mode=FetchMode.STATIC)
    pages = [[_job("1")], [_job("2")], [_job("late")]]
    run_company(
        FakeScraper([[_job("1")], [_job("2")]], config=config),
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: u,
    )
    result = run_company(
        FakeScraper(pages, config=config), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: u
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


def test_default_fetch_page_routes_rendered_xhr_with_its_engine(monkeypatch):
    from jobwatch import engine as engine_module

    seen = {}

    def fake_fetch_rendered_xhr(url, *, capture_response_url, engine, browser):
        seen.update(
            url=url, capture=capture_response_url, engine=engine, browser=browser
        )
        return "{}"

    monkeypatch.setattr(engine_module, "fetch_rendered_xhr", fake_fetch_rendered_xhr)
    config = CompanyConfig(
        name="Acme",
        career_url="https://acme.example/careers",
        fetch_mode=FetchMode.RENDERED_XHR,
        capture_response_url="/api/state",
        browser_engine="firefox",
    )

    payload = engine_module.default_fetch_page(config, config.career_url, browser="B")

    assert payload == "{}"
    # The engine must reach the fetch layer: routing a firefox-only board to the
    # default chromium is exactly the failure this config exists to prevent.
    assert seen == {
        "url": "https://acme.example/careers",
        "capture": "/api/state",
        "engine": "firefox",
        "browser": "B",
    }


def test_seed_run_that_truncated_is_not_saved(tmp_path):
    # Saving it would record part of the board as all of it, so every posting
    # the run never reached is reported as new on the next run.
    pages = [[Job("Acme", str(i), f"Job {i}", f"https://x/{i}")] for i in range(3)]
    scraper = FakeScraper(pages)

    def failing_fetch(config, url):
        if url == "2":
            raise FetchError("boom")
        return url

    result = run_company(scraper, store=JsonSnapshotStore(tmp_path), fetch_page=failing_fetch)

    assert result.status == "failed"
    assert "not saved" in result.detail
    assert not snapshot_path("Acme", state_dir=tmp_path).exists()


def test_company_can_override_the_inter_page_delay():
    from jobwatch.engine import _fetch_all_pages

    slept = []
    config = CompanyConfig(
        name="Acme", career_url="0", fetch_mode=FetchMode.STATIC,
        inter_page_delay_seconds=1.5,
    )
    pages = [[Job("Acme", str(i), f"Job {i}", f"https://x/{i}")] for i in range(3)]

    _fetch_all_pages(
        FakeScraper(pages, config), config,
        known_ids=None, fetch_page=lambda c, u: u, sleep=slept.append,
    )

    assert slept and set(slept) == {1.5}


class EnrichingScraper(FakeScraper):
    """Listing pages carry ids only; each job's detail page carries its title.

    Detail URLs are "detail:<job_id>" so the fetch stub can tell them apart from
    the numeric page indexes FakeScraper uses.
    """

    def __init__(self, pages, config=None, fail_ids=(), no_detail_ids=()):
        super().__init__(pages, config)
        self.detail_fetches: list[str] = []
        self._fail_ids = set(fail_ids)
        self._no_detail_ids = set(no_detail_ids)

    def detail_url(self, job):
        if job.job_id in self._no_detail_ids:
            return None
        return f"detail:{job.job_id}"

    def parse_detail(self, payload: str, job):
        if job.job_id in self._fail_ids:
            raise ValueError("detail page did not parse")
        from dataclasses import replace

        return replace(job, title=f"Real Title {job.job_id}")


def _enriching_fetch(scraper):
    def fetch_page(config, url):
        if url.startswith("detail:"):
            scraper.detail_fetches.append(url)
            return url
        return url

    return fetch_page


def test_new_jobs_are_enriched_from_their_detail_pages(tmp_path):
    scraper = EnrichingScraper([[_job("1", title="placeholder")]])
    save_snapshot("Acme", {"0": {}}, tmp_path)
    result = run_company(
        scraper, store=JsonSnapshotStore(tmp_path), fetch_page=_enriching_fetch(scraper)
    )
    assert [j.title for j in result.new_jobs] == ["Real Title 1"]
    assert scraper.detail_fetches == ["detail:1"]


def test_enriched_title_is_what_gets_persisted(tmp_path):
    # The snapshot must hold the enriched record, not the placeholder, or the
    # stored history of the board is permanently thinner than what was reported.
    scraper = EnrichingScraper([[_job("1", title="placeholder")]])
    save_snapshot("Acme", {"0": {}}, tmp_path)
    run_company(scraper, store=JsonSnapshotStore(tmp_path), fetch_page=_enriching_fetch(scraper))
    assert load_snapshot("Acme", tmp_path)["1"]["title"] == "Real Title 1"


def test_already_seen_jobs_are_not_re_fetched(tmp_path):
    # The whole point of enriching after the diff: a routine run costs one
    # detail fetch per genuinely new posting, not one per posting on the board.
    scraper = EnrichingScraper([[_job("1"), _job("2"), _job("3")]])
    save_snapshot("Acme", {"1": {}, "2": {}}, tmp_path)
    run_company(scraper, store=JsonSnapshotStore(tmp_path), fetch_page=_enriching_fetch(scraper))
    assert scraper.detail_fetches == ["detail:3"]


def test_a_failed_detail_fetch_keeps_the_listing_job(tmp_path):
    scraper = EnrichingScraper([[_job("1", title="placeholder"), _job("2")]])
    save_snapshot("Acme", {"0": {}}, tmp_path)

    def fetch_page(config, url):
        if url == "detail:1":
            raise FetchError("detail page timed out")
        return url

    result = run_company(scraper, store=JsonSnapshotStore(tmp_path), fetch_page=fetch_page)
    titles = {j.job_id: j.title for j in result.new_jobs}
    assert titles["1"] == "placeholder"  # kept, not dropped
    assert titles["2"] == "Real Title 2"
    assert result.status == "ok"


def test_a_raising_parse_detail_does_not_fail_the_company(tmp_path):
    scraper = EnrichingScraper([[_job("1", title="placeholder")]], fail_ids={"1"})
    save_snapshot("Acme", {"0": {}}, tmp_path)
    result = run_company(
        scraper, store=JsonSnapshotStore(tmp_path), fetch_page=_enriching_fetch(scraper)
    )
    assert result.status == "ok"
    assert [j.title for j in result.new_jobs] == ["placeholder"]


def test_scrapers_without_a_detail_url_make_no_extra_fetches(tmp_path):
    # Every other company in the registry takes this path.
    scraper = FakeScraper([[_job("1")]])
    fetched: list[str] = []

    def fetch_page(config, url):
        fetched.append(url)
        return url

    save_snapshot("Acme", {"0": {}}, tmp_path)
    result = run_company(scraper, store=JsonSnapshotStore(tmp_path), fetch_page=fetch_page)
    assert fetched == ["0"]
    assert [j.job_id for j in result.new_jobs] == ["1"]


def test_a_job_whose_detail_url_is_none_is_skipped(tmp_path):
    scraper = EnrichingScraper([[_job("1"), _job("2")]], no_detail_ids={"1"})
    save_snapshot("Acme", {"0": {}}, tmp_path)
    result = run_company(
        scraper, store=JsonSnapshotStore(tmp_path), fetch_page=_enriching_fetch(scraper)
    )
    assert scraper.detail_fetches == ["detail:2"]
    assert {j.job_id: j.title for j in result.new_jobs}["1"] == "Software Engineer"


def test_enrichment_stops_at_the_configured_ceiling(tmp_path):
    # A board that suddenly reports hundreds of new jobs must not turn into
    # hundreds of requests.
    config = CompanyConfig(
        name="Acme",
        career_url="0",
        fetch_mode=FetchMode.STATIC,
        max_enrichment_fetches=2,
    )
    scraper = EnrichingScraper([[_job(str(i)) for i in range(5)]], config=config)
    save_snapshot("Acme", {"99": {}}, tmp_path)
    result = run_company(
        scraper, store=JsonSnapshotStore(tmp_path), fetch_page=_enriching_fetch(scraper)
    )
    assert len(scraper.detail_fetches) == 2
    enriched = [j for j in result.new_jobs if j.title.startswith("Real Title")]
    assert len(enriched) == 2
    assert len(result.new_jobs) == 5  # the rest are reported unenriched, not dropped


def test_a_seed_run_enriches_the_whole_board_once(tmp_path):
    # On a seed every job is new, so the seed pays for the board and later runs
    # only pay for the day's postings.
    scraper = EnrichingScraper([[_job("1"), _job("2")]])
    result = run_company(
        scraper, store=JsonSnapshotStore(tmp_path), fetch_page=_enriching_fetch(scraper)
    )
    assert result.status == "seeded"
    assert sorted(scraper.detail_fetches) == ["detail:1", "detail:2"]
    assert load_snapshot("Acme", tmp_path)["1"]["title"] == "Real Title 1"


class WrappingScraper(FakeScraper):
    """A board that answers any page past its end with page 1 again instead of
    a short page — what Target's and Tempus's Workday tenants do, and what
    leaves next_page_url with no exhaustion signal to return None on."""

    def __init__(self, pages, config=None):
        super().__init__(pages, config)
        self._real_pages = len(pages)

    def parse(self, payload: str) -> list[Job]:
        return self._pages[int(payload) % self._real_pages]

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        return str(int(payload) + 1)


def test_a_board_that_repeats_a_served_page_stops_instead_of_hitting_the_ceiling(tmp_path):
    calls = []

    def counting_fetch(config, url):
        calls.append(url)
        return url

    pages = [[_job("1")], [_job("2")], [_job("3")]]
    result = run_company(
        WrappingScraper(pages), store=JsonSnapshotStore(tmp_path), fetch_page=counting_fetch
    )

    # Three real pages, then the wrapped page 1 that triggers the stop.
    assert len(calls) == 4
    assert result.status == "seeded"
    assert result.total_jobs == 3
    # The seed is saved, not discarded: the board is exhausted, not truncated.
    assert result.detail is None
    assert set(load_snapshot("Acme", tmp_path)) == {"1", "2", "3"}


def test_the_repeat_stop_applies_even_when_paginate_fully_is_set(tmp_path):
    # paginate_fully is about jobs seen on a previous run, not about a board
    # repeating itself inside one pass, so it must not defeat this stop.
    config = CompanyConfig(
        name="Unsorted",
        career_url="0",
        fetch_mode=FetchMode.STATIC,
        paginate_fully=True,
    )
    calls = []

    def counting_fetch(c, url):
        calls.append(url)
        return url

    pages = [[_job("1")], [_job("2")]]
    result = run_company(
        WrappingScraper(pages, config=config), store=JsonSnapshotStore(tmp_path), fetch_page=counting_fetch
    )
    assert len(calls) == 3
    assert result.total_jobs == 2


def test_a_page_repeating_only_some_ids_keeps_paginating(tmp_path):
    # Overlapping pages are normal on boards that shift while being read. Only
    # a page that adds nothing at all should stop the run.
    pages = [[_job("1"), _job("2")], [_job("2"), _job("3")], [_job("3"), _job("4")]]
    result = run_company(
        FakeScraper(pages), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: u
    )
    assert result.total_jobs == 4


def test_an_empty_later_page_still_ends_the_run_without_the_repeat_stop(tmp_path):
    # An empty page adds no ids, but it is the ordinary end-of-board signal and
    # must not be mistaken for a repeat — the jobs already collected stand.
    pages = [[_job("1")], []]
    result = run_company(
        FakeScraper(pages), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: u
    )
    assert result.total_jobs == 1
    assert result.status == "seeded"


def test_a_run_that_stopped_on_a_known_page_is_not_suspicious(tmp_path):
    """The Microsoft case: a newest-first board where a lot is genuinely new.

    The ratio is new jobs over jobs *read*, and the read stops at the first page
    holding nothing unseen — so a company that posts heavily reads mostly-new
    pages and the ratio approaches 1 no matter how healthy the run is. Reaching
    a page of entirely known jobs proves the ids still line up, which is what
    the guard is trying to establish, so it must not fire.
    """
    run_company(
        FakeScraper([[_job("k1"), _job("k2")]]),
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: u,
    )
    pages = [
        [_job(f"new-{i}") for i in range(20)],  # all unseen
        [_job("k1"), _job("k2")],               # nothing unseen: ends the run
        [_job("never-read")],                   # so the stop is a choice, not the end
    ]
    result = run_company(
        FakeScraper(pages), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: u
    )

    assert result.total_jobs == 22
    assert len(result.new_jobs) == 20          # 20/22 = 0.91, over the ratio
    assert result.status == "ok"
    # The real cost of a false positive: the snapshot must still be written, or
    # these 20 report again on every future run.
    assert set(load_snapshot("Acme", tmp_path)) >= {"k1", "k2", "new-0", "new-19"}


def test_a_multi_page_run_that_never_meets_a_known_job_is_still_suspicious(tmp_path):
    # A real scheme change: no page matches the snapshot, so the run never
    # early-stops and reads to the end of the board.
    run_company(
        FakeScraper([[_job(f"old-{i}") for i in range(20)]]),
        store=JsonSnapshotStore(tmp_path),
        fetch_page=lambda c, u: u,
    )
    pages = [
        [_job(f"new-{i}") for i in range(20)],
        [_job(f"new-{i}") for i in range(20, 40)],
    ]
    result = run_company(
        FakeScraper(pages), store=JsonSnapshotStore(tmp_path), fetch_page=lambda c, u: u
    )
    assert result.status == "suspicious"
    assert "scheme change" in result.detail
    # And the snapshot is withheld, which is the point of the guard.
    assert set(load_snapshot("Acme", tmp_path)) == {f"old-{i}" for i in range(20)}
