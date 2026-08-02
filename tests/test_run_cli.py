import json

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

import run as cli


class _OneJobScraper(Scraper):
    config = CompanyConfig(
        name="TestCo", career_url="https://example.com/jobs", fetch_mode=FetchMode.STATIC
    )

    def parse(self, payload: str) -> list[Job]:
        return [Job(company="TestCo", job_id="1", title="Software Engineer", url="https://example.com/1")]


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

    exit_code = cli.main([])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "BrokenCo" in out
    assert "TestCo" in out
    report_files = list((tmp_path / "output").glob("*.json"))
    assert len(report_files) == 1
    assert "TestCo" in report_files[0].read_text()


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

    exit_code = cli.main([])

    assert exit_code == 1
    report_files = list((tmp_path / "output").glob("*.json"))
    assert len(report_files) == 1
    payload = json.loads(report_files[0].read_text())
    by_company = {entry["company"]: entry for entry in payload}
    assert by_company["TestCo"]["status"] == "seeded"
    assert by_company["RenderCo"]["status"] == "failed"
    assert "launch" in by_company["RenderCo"]["detail"].lower()
