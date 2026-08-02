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
