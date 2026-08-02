from jobwatch.engine import MAX_PAGES, run_company
from jobwatch.fetch import FetchBlocked, FetchError
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper
from jobwatch.state import load_snapshot, snapshot_path


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


def test_empty_first_run_persists_seed_state_and_reports_future_jobs(tmp_path):
    run_company(FakeScraper([[]]), state_dir=tmp_path, fetch_page=lambda c, u: "0")

    result = run_company(
        FakeScraper([[_job("1")]]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )

    assert result.status == "ok"
    assert [job.job_id for job in result.new_jobs] == ["1"]


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
    run_company(
        FakeScraper([[_job(str(i)) for i in range(10)]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: "0",
    )
    mostly_new_jobs = [_job(str(i)) for i in range(2)] + [_job(f"new-{i}") for i in range(8)]
    result = run_company(
        FakeScraper([mostly_new_jobs]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    assert result.status == "suspicious"
