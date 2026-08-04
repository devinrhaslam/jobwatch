import json

import pytest

import jobwatch.filters as filters
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

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
