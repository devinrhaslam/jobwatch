import json

import pytest

import jobwatch.filters as filters
from jobwatch.fetch import FetchError
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper
from jobwatch.store import JsonSnapshotStore

import run as cli

# Titles a stub classifier treats as off-target, standing in for the specialised
# tracks the real filter drops.
_OFF_TARGET_MARKERS = ("Data Engineer", "Engineering Manager", "Security Engineer")


def _stub_classify(jobs):
    return [
        filters.Verdict(
            not any(marker in job.title for marker in _OFF_TARGET_MARKERS),
            "stubbed verdict",
        )
        for job in jobs
    ]


@pytest.fixture(autouse=True)
def never_call_claude(monkeypatch):
    """The CLI runs the real filter, so every test in this file would otherwise
    hit the network. Patch the classifier itself rather than apply_filters, so
    the CLI's own filter wiring is still exercised."""
    monkeypatch.setattr(filters, "classify_with_claude", _stub_classify)


@pytest.fixture(autouse=True)
def _no_postgres_env(monkeypatch):
    """Keep every CLI test on the JSON backend regardless of the developer's
    shell. If JOBWATCH_DATABASE_URL happened to be exported, main() would try to
    open a real database instead of writing the tmp_path snapshots these tests
    assert on."""
    monkeypatch.delenv("JOBWATCH_DATABASE_URL", raising=False)


def test_build_store_defaults_to_json_when_env_is_unset():
    assert isinstance(cli._build_store(), JsonSnapshotStore)


def test_build_store_uses_postgres_only_when_env_is_set(monkeypatch):
    captured = {}

    class _FakePostgres:
        def __init__(self, dsn):
            captured["dsn"] = dsn

    monkeypatch.setattr(cli, "PostgresSnapshotStore", _FakePostgres)
    monkeypatch.setenv("JOBWATCH_DATABASE_URL", "postgresql://user:pw@host/db")

    store = cli._build_store()
    assert isinstance(store, _FakePostgres)
    assert captured["dsn"] == "postgresql://user:pw@host/db"


class _OneJobScraper(Scraper):
    config = CompanyConfig(
        name="TestCo", career_url="https://example.com/jobs", fetch_mode=FetchMode.STATIC
    )

    def parse(self, payload: str) -> list[Job]:
        return [Job(company="TestCo", job_id="1", title="Software Engineer", url="https://example.com/1")]


class _OneJobScraper2(Scraper):
    config = CompanyConfig(
        name="TestCo2", career_url="https://example.com/jobs2", fetch_mode=FetchMode.STATIC
    )

    def parse(self, payload: str) -> list[Job]:
        return [Job(company="TestCo2", job_id="1", title="Software Engineer", url="https://example.com/2/1")]


class _CrashingScraper(Scraper):
    config = CompanyConfig(
        name="BrokenCo", career_url="https://example.com/jobs", fetch_mode=FetchMode.STATIC
    )

    def parse(self, payload: str) -> list[Job]:
        raise RuntimeError("boom")


class _SuspiciousScraper(Scraper):
    """Seeds 20 jobs, then returns 20 entirely different job IDs to trip the
    suspicious-volume guard on the second run."""

    config = CompanyConfig(
        name="SuspiciousCo", career_url="https://example.com/jobs", fetch_mode=FetchMode.STATIC
    )

    def __init__(self):
        self._call_count = 0

    def parse(self, payload: str) -> list[Job]:
        self._call_count += 1
        prefix = "old" if self._call_count == 1 else "new"
        return [
            Job(
                company="SuspiciousCo",
                job_id=f"{prefix}-{i}",
                title="Engineer",
                url=f"https://example.com/{prefix}-{i}",
            )
            for i in range(20)
        ]


class _MixedRelevanceScraper(Scraper):
    """Seeds one job, then adds one relevant and one off-target job."""

    config = CompanyConfig(
        name="MixedCo", career_url="https://example.com/jobs", fetch_mode=FetchMode.STATIC
    )

    def __init__(self):
        self._call_count = 0

    def parse(self, payload: str) -> list[Job]:
        self._call_count += 1
        jobs = [
            Job(
                company="MixedCo",
                job_id=f"seed-{i}",
                title="Software Engineer",
                url=f"https://example.com/seed-{i}",
            )
            for i in range(10)
        ]
        if self._call_count > 1:
            jobs.append(
                Job(
                    company="MixedCo",
                    job_id="relevant",
                    title="Senior Software Engineer, Payments",
                    url="https://example.com/relevant",
                )
            )
            jobs.append(
                Job(
                    company="MixedCo",
                    job_id="offtarget",
                    title="Data Engineer, Analytics",
                    url="https://example.com/offtarget",
                )
            )
        return jobs


class _RenderedScraper(Scraper):
    config = CompanyConfig(
        name="RenderCo",
        career_url="https://example.com/jobs",
        fetch_mode=FetchMode.RENDERED,
        wait_for_selector=".job",
    )

    def parse(self, payload: str) -> list[Job]:
        return [Job(company="RenderCo", job_id="1", title="Engineer", url="https://example.com/1")]


class _FailingChromium:
    def launch(self):
        raise RuntimeError("Executable doesn't exist")


class _FakePlaywright:
    chromium = _FailingChromium()


class _FakePlaywrightContextManager:
    def __enter__(self):
        return _FakePlaywright()

    def __exit__(self, *exc_info):
        return False


def test_main_runs_registered_company_and_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SCRAPERS", {"TestCo": _OneJobScraper()})
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )

    exit_code = cli.main(["--company", "TestCo"])

    assert exit_code == 0
    reports = list((tmp_path / "output").glob("*.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text())
    assert payload[0]["company"] == "TestCo"


class _RecordingStore:
    """Wraps a real store but captures record_run calls, so a test can assert the
    ingestion loop reports each company's outcome for the health view."""

    def __init__(self, inner):
        self.inner = inner
        self.runs: list[tuple] = []

    def exists(self, company):
        return self.inner.exists(company)

    def load(self, company):
        return self.inner.load(company)

    def save(self, company, jobs, now=None):
        return self.inner.save(company, jobs, now)

    def close(self):
        return self.inner.close()

    def record_run(self, company, status, jobs_read=0, jobs_new=0, error=None):
        self.runs.append((company, status, jobs_read, jobs_new, error))


def test_main_records_a_company_run_for_the_health_view(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SCRAPERS", {"TestCo": _OneJobScraper()})
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )
    recording = _RecordingStore(JsonSnapshotStore(tmp_path / "state"))
    monkeypatch.setattr(cli, "_build_store", lambda: recording)

    cli.main(["--company", "TestCo"])

    assert len(recording.runs) == 1
    company, status, jobs_read, jobs_new, _ = recording.runs[0]
    assert company == "TestCo"
    assert status == "seeded"  # first run seeds the company
    assert jobs_read == 1


def test_dry_run_does_not_record_a_company_run(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SCRAPERS", {"TestCo": _OneJobScraper()})
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )
    recording = _RecordingStore(JsonSnapshotStore(tmp_path / "state"))
    monkeypatch.setattr(cli, "_build_store", lambda: recording)

    cli.main(["--company", "TestCo", "--dry-run"])

    assert recording.runs == []


class _HangingScraper(Scraper):
    config = CompanyConfig(
        name="HangCo", career_url="https://example.com/jobs", fetch_mode=FetchMode.STATIC
    )

    def parse(self, payload: str) -> list[Job]:
        import time as _time

        _time.sleep(10)  # longer than the patched per-company timeout
        return []


def test_company_exceeding_timeout_is_failed_without_aborting_the_run(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli, "SCRAPERS", {"HangCo": _HangingScraper(), "TestCo": _OneJobScraper()}
    )
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )
    monkeypatch.setattr(cli, "COMPANY_TIMEOUT_SECONDS", 1)

    exit_code = cli.main(["--company", "HangCo", "--company", "TestCo"])

    # The hung company failed (non-zero exit), but the next company still ran.
    assert exit_code != 0
    err = capsys.readouterr().err
    assert "HangCo" in err and "FAILED" in err
    assert "seeded 1" in err  # TestCo was reached and seeded


def test_skip_browser_excludes_rendered_companies_without_launching_a_browser(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli, "SCRAPERS", {"RenderCo": _RenderedScraper(), "TestCo": _OneJobScraper()}
    )
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )

    def _no_browser():
        raise AssertionError("browser must not be launched when skipping")

    monkeypatch.setattr(cli, "sync_playwright", _no_browser)

    exit_code = cli.main(["--skip-browser"])

    err = capsys.readouterr().err
    assert "Skipping" in err and "RenderCo" in err
    assert "seeded 1" in err  # the static company still ran
    assert exit_code == 0


def test_main_returns_error_code_for_unknown_company(monkeypatch, capsys):
    monkeypatch.setattr(cli, "SCRAPERS", {"TestCo": _OneJobScraper()})
    exit_code = cli.main(["--company", "DoesNotExist"])
    assert exit_code == 2
    assert "Unknown companies" in capsys.readouterr().err


def test_one_company_crashing_does_not_abort_the_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "SCRAPERS", {"BrokenCo": _CrashingScraper(), "TestCo": _OneJobScraper()}
    )
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )
    monkeypatch.setattr(cli, "sleep", lambda seconds: None)

    exit_code = cli.main([])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "BrokenCo" in out
    assert "TestCo" in out
    report_files = list((tmp_path / "output").glob("*.json"))
    assert len(report_files) == 1
    assert "TestCo" in report_files[0].read_text()


def test_sleeps_between_companies_but_not_after_the_last(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli, "SCRAPERS", {"TestCo": _OneJobScraper(), "TestCo2": _OneJobScraper2()}
    )
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )
    sleeps = []
    monkeypatch.setattr(cli, "sleep", lambda seconds: sleeps.append(seconds))

    cli.main([])

    assert sleeps == [cli.INTER_COMPANY_DELAY_SECONDS]


def test_does_not_sleep_for_a_single_company(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SCRAPERS", {"TestCo": _OneJobScraper()})
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )
    sleeps = []
    monkeypatch.setattr(cli, "sleep", lambda seconds: sleeps.append(seconds))

    cli.main([])

    assert sleeps == []


def test_suspicious_result_returns_nonzero_exit_code(tmp_path, monkeypatch):
    scraper = _SuspiciousScraper()
    monkeypatch.setattr(cli, "SCRAPERS", {"SuspiciousCo": scraper})
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )

    first_exit_code = cli.main(["--company", "SuspiciousCo"])
    assert first_exit_code == 0

    second_exit_code = cli.main(["--company", "SuspiciousCo"])

    assert second_exit_code != 0


def _run_mixed_company(tmp_path, monkeypatch, argv):
    monkeypatch.setattr(cli, "SCRAPERS", {"MixedCo": _MixedRelevanceScraper()})
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )
    cli.main(argv)
    cli.main(argv)
    return json.loads(next((tmp_path / "output").glob("*.json")).read_text())


def test_report_omits_jobs_that_do_not_match_the_role_filter(tmp_path, monkeypatch):
    payload = _run_mixed_company(tmp_path, monkeypatch, ["--company", "MixedCo"])
    reported = {job["job_id"] for job in payload[0]["new_jobs"]}
    assert reported == {"relevant"}


def test_all_roles_flag_reports_every_new_job(tmp_path, monkeypatch):
    payload = _run_mixed_company(
        tmp_path, monkeypatch, ["--company", "MixedCo", "--all-roles"]
    )
    reported = {job["job_id"] for job in payload[0]["new_jobs"]}
    assert reported == {"relevant", "offtarget"}


def test_filtered_out_jobs_are_still_recorded_in_the_snapshot(tmp_path, monkeypatch):
    _run_mixed_company(tmp_path, monkeypatch, ["--company", "MixedCo"])
    snapshot = json.loads((tmp_path / "state" / "mixedco.json").read_text())
    assert "offtarget" in snapshot


def _run_mixed_with_failing_filter(tmp_path, monkeypatch, capsys):
    def failing(jobs):
        raise filters.FilterError("classification request failed")

    monkeypatch.setattr(cli, "SCRAPERS", {"MixedCo": _MixedRelevanceScraper()})
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )
    cli.main(["--company", "MixedCo"])  # seed run
    monkeypatch.setattr(filters, "classify_with_claude", failing)
    exit_code = cli.main(["--company", "MixedCo"])
    return exit_code, capsys.readouterr()


def test_filter_failure_returns_nonzero_exit_code(tmp_path, monkeypatch, capsys):
    exit_code, _ = _run_mixed_with_failing_filter(tmp_path, monkeypatch, capsys)
    assert exit_code != 0


def test_filter_failure_still_reports_the_days_jobs_unfiltered(tmp_path, monkeypatch, capsys):
    # Snapshots are written before filtering, so these jobs will never be
    # reported again. Losing them to a failed API call would be silent data loss.
    _, captured = _run_mixed_with_failing_filter(tmp_path, monkeypatch, capsys)
    assert "https://example.com/relevant" in captured.out
    assert "https://example.com/offtarget" in captured.out
    assert "Role filter failed" in captured.err


def test_browser_launch_failure_still_reports_static_company(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli, "SCRAPERS", {"TestCo": _OneJobScraper(), "RenderCo": _RenderedScraper()}
    )
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(
        cli, "default_fetch_page", lambda config, url, browser=None: "<html></html>"
    )
    monkeypatch.setattr(cli, "sync_playwright", lambda: _FakePlaywrightContextManager())
    monkeypatch.setattr(cli, "sleep", lambda seconds: None)

    exit_code = cli.main([])

    assert exit_code == 1
    report_files = list((tmp_path / "output").glob("*.json"))
    assert len(report_files) == 1
    payload = json.loads(report_files[0].read_text())
    by_company = {entry["company"]: entry for entry in payload}
    assert by_company["TestCo"]["status"] == "seeded"
    assert by_company["RenderCo"]["status"] == "failed"
    assert "launch" in by_company["RenderCo"]["detail"].lower()


class _StubBrowser:
    def __init__(self, engine):
        self.engine = engine
        self.closed = False

    def close(self):
        self.closed = True


class _StubEngine:
    def __init__(self, name, fail=False):
        self.name = name
        self.fail = fail
        self.launches = 0

    def launch(self):
        self.launches += 1
        if self.fail:
            raise RuntimeError("Executable doesn't exist")
        return _StubBrowser(self.name)


class _StubPlaywright:
    def __init__(self, **engines):
        for name, engine in engines.items():
            setattr(self, name, engine)


def test_browser_pool_launches_each_engine_once_and_closes_them():
    chromium = _StubEngine("chromium")
    firefox = _StubEngine("firefox")
    pool = cli._BrowserPool(_StubPlaywright(chromium=chromium, firefox=firefox))

    first = pool.get("chromium")
    again = pool.get("chromium")
    other = pool.get("firefox")

    assert first is again  # reused across companies rather than relaunched
    assert other.engine == "firefox"
    assert (chromium.launches, firefox.launches) == (1, 1)

    pool.close()
    assert first.closed and other.closed


def test_browser_pool_does_not_launch_an_engine_no_company_needs():
    chromium = _StubEngine("chromium")
    firefox = _StubEngine("firefox")
    pool = cli._BrowserPool(_StubPlaywright(chromium=chromium, firefox=firefox))

    pool.get("chromium")

    assert firefox.launches == 0


def test_browser_pool_reports_a_launch_failure_without_retrying_it():
    firefox = _StubEngine("firefox", fail=True)
    pool = cli._BrowserPool(_StubPlaywright(firefox=firefox))

    for _ in range(2):
        with pytest.raises(FetchError, match="browser launch failed for firefox"):
            pool.get("firefox")

    # A missing browser binary will not appear mid-run, so re-attempting the
    # launch for every page would only slow the run down.
    assert firefox.launches == 1


def test_one_engine_failing_to_launch_leaves_another_engines_company_working():
    chromium = _StubEngine("chromium")
    firefox = _StubEngine("firefox", fail=True)
    pool = cli._BrowserPool(_StubPlaywright(chromium=chromium, firefox=firefox))

    with pytest.raises(FetchError):
        pool.get("firefox")

    assert pool.get("chromium").engine == "chromium"


# --- progress reporting -----------------------------------------------------


def test_progress_line_names_each_company_with_a_counter(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SCRAPERS", {"TestCo": _OneJobScraper()})
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(cli, "default_fetch_page", lambda config, url: "payload")
    monkeypatch.setattr(cli, "sleep", lambda seconds: None)

    cli.main(["--dry-run"])
    err = capsys.readouterr().err
    assert "[  1/1] TestCo" in err
    assert "Scraped 1 companies in" in err


def test_progress_reports_a_dot_per_request(tmp_path, monkeypatch, capsys):
    # The point of the dots: a company making 185 requests should look busy
    # rather than hung.
    class _ThreePageScraper(Scraper):
        config = CompanyConfig(
            name="Pager", career_url="0", fetch_mode=FetchMode.STATIC
        )

        def parse(self, payload):
            return [
                Job(
                    company="Pager",
                    job_id=f"{payload}-1",
                    title="Engineer",
                    url="https://example.com/1",
                )
            ]

        def next_page_url(self, payload, current_url):
            nxt = int(payload) + 1
            return str(nxt) if nxt < 3 else None

    monkeypatch.setattr(cli, "SCRAPERS", {"Pager": _ThreePageScraper()})
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(cli, "default_fetch_page", lambda config, url: url)
    monkeypatch.setattr(cli, "sleep", lambda seconds: None)

    cli.main(["--dry-run", "--all-roles"])
    line = [ln for ln in capsys.readouterr().err.splitlines() if "Pager" in ln][0]
    assert line.count(".") >= 3


def test_progress_goes_to_stderr_not_the_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SCRAPERS", {"TestCo": _OneJobScraper()})
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(cli, "default_fetch_page", lambda config, url: "payload")
    monkeypatch.setattr(cli, "sleep", lambda seconds: None)

    cli.main(["--dry-run"])
    captured = capsys.readouterr()
    assert "[  1/1]" not in captured.out
    assert "Scraped" not in captured.out


def test_outcome_wording_distinguishes_seeding_from_reading():
    from jobwatch.engine import CompanyResult

    job = Job(company="X", job_id="1", title="T", url="u")
    assert cli._outcome(CompanyResult("X", "seeded", [], 40)) == "seeded 40"
    assert cli._outcome(CompanyResult("X", "ok", [], 40)) == "read 40"
    assert cli._outcome(CompanyResult("X", "ok", [job], 40)) == "read 40, 1 new"
    assert cli._outcome(CompanyResult("X", "failed", [], 0)) == "FAILED"
    assert cli._outcome(CompanyResult("X", "blocked", [], 0)) == "BLOCKED"
    assert cli._outcome(CompanyResult("X", "suspicious", [job], 40)) == "SUSPICIOUS"


def test_a_filter_crash_still_reports_the_jobs(tmp_path, monkeypatch, capsys):
    # An unset ANTHROPIC_API_KEY raises TypeError from the SDK, not FilterError.
    # Snapshots are written before this point, so letting it propagate would
    # lose the day's jobs permanently.
    def _boom(jobs):
        raise TypeError("Could not resolve authentication method")

    class _GrowingScraper(Scraper):
        """Seeds one job, then offers a second one so the next run has something
        for the filter to choke on."""

        config = CompanyConfig(
            name="TestCo", career_url="https://example.com", fetch_mode=FetchMode.STATIC
        )

        def __init__(self):
            self.runs = 0

        def parse(self, payload):
            self.runs += 1
            ids = ["1"] if self.runs == 1 else ["1", "2"]
            return [
                Job(
                    company="TestCo",
                    job_id=i,
                    title="Software Engineer",
                    url=f"https://example.com/{i}",
                )
                for i in ids
            ]

    monkeypatch.setattr(filters, "classify_with_claude", _boom)
    monkeypatch.setattr(cli, "SCRAPERS", {"TestCo": _GrowingScraper()})
    monkeypatch.setattr(cli, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(cli, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(cli, "default_fetch_page", lambda config, url: "payload")
    monkeypatch.setattr(cli, "sleep", lambda seconds: None)

    cli.main([])  # seeds and persists
    exit_code = cli.main(["--dry-run"])

    captured = capsys.readouterr()
    assert "Role filter failed: TypeError" in captured.err
    assert "Reporting every new job unfiltered" in captured.err
    assert "Software Engineer" in captured.out  # the job survived
    assert exit_code == 1
