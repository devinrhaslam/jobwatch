"""Integration tests for PostgresSnapshotStore against a real Postgres.

Gated on JOBWATCH_TEST_DATABASE_URL so the default suite stays infra-free: with
no database configured these skip, and the 810 unit tests run untouched. To run
them, bring up docker-compose and point this at a throwaway database:

    JOBWATCH_TEST_DATABASE_URL=postgresql://jobwatch:jobwatch@localhost:5432/jobwatch_test \\
        .venv/bin/pytest tests/test_store_postgres.py
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

from jobwatch.engine import run_company
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper
from jobwatch.store import PostgresSnapshotStore

TEST_DSN = os.environ.get("JOBWATCH_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="set JOBWATCH_TEST_DATABASE_URL to a throwaway database to run these",
)

SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text()


class _FakeScraper(Scraper):
    """Pages addressed by index; the fetch stub echoes the index as payload, so
    parse()/next_page_url() stay pure. Mirrors tests/test_engine.py's fake."""

    def __init__(self, pages: list[list[Job]], name: str = "Acme"):
        self.config = CompanyConfig(name=name, career_url="0", fetch_mode=FetchMode.STATIC)
        self._pages = pages

    def parse(self, payload: str) -> list[Job]:
        return self._pages[int(payload)]

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        nxt = int(payload) + 1
        return str(nxt) if nxt < len(self._pages) else None


def _job(job_id: str, title: str = "Software Engineer") -> Job:
    return Job(company="Acme", job_id=job_id, title=title, url=f"https://acme.example/{job_id}")


def _statements(sql: str) -> list[str]:
    # psycopg's extended protocol allows one statement per execute, so schema.sql
    # is split on ';'. Comment lines are dropped first, since prose comments
    # contain semicolons that would otherwise split mid-sentence; the SQL
    # statements themselves carry no embedded semicolons.
    body = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with psycopg.connect(TEST_DSN, autocommit=True) as conn:
        for statement in _statements(SCHEMA):
            conn.execute(statement)


@pytest.fixture
def store():
    with psycopg.connect(TEST_DSN, autocommit=True) as conn:
        conn.execute("TRUNCATE jobs, company_runs")
    s = PostgresSnapshotStore(TEST_DSN)
    yield s
    s.close()


def test_exists_is_false_before_any_save_and_true_after(store):
    assert store.exists("Acme") is False
    store.save("Acme", [_job("1")])
    assert store.exists("Acme") is True


def test_save_then_load_round_trips_the_snapshot(store):
    store.save("Acme", [_job("1"), _job("2", title="Backend Engineer")])
    snapshot = store.load("Acme")
    assert set(snapshot) == {"1", "2"}
    assert snapshot["2"]["title"] == "Backend Engineer"
    assert snapshot["1"]["first_seen"] and snapshot["1"]["last_seen"]


def test_first_seen_is_preserved_while_mutable_fields_and_last_seen_move(store):
    early = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later = datetime(2026, 8, 1, tzinfo=timezone.utc)
    store.save("Acme", [Job("Acme", "1", "Old Title", "https://acme.example/1")], now=early)
    store.save("Acme", [Job("Acme", "1", "New Title", "https://acme.example/1")], now=later)

    snapshot = store.load("Acme")
    assert snapshot["1"]["title"] == "New Title"
    assert snapshot["1"]["first_seen"].startswith("2026-01-01")
    assert snapshot["1"]["last_seen"].startswith("2026-08-01")


def test_two_consecutive_ingests_report_zero_new(store):
    # The trust property the whole tool rests on, now proved against Postgres.
    scraper = _FakeScraper([[_job("1"), _job("2")]])
    first = run_company(scraper, store=store, fetch_page=lambda c, u: "0")
    assert first.status == "seeded"
    assert first.new_jobs == []

    second = run_company(scraper, store=store, fetch_page=lambda c, u: "0")
    assert second.status == "ok"
    assert second.new_jobs == []


def test_a_posting_added_after_seeding_is_reported_once(store):
    run_company(_FakeScraper([[_job("1")]]), store=store, fetch_page=lambda c, u: "0")
    appeared = run_company(
        _FakeScraper([[_job("1"), _job("2")]]), store=store, fetch_page=lambda c, u: "0"
    )
    assert [j.job_id for j in appeared.new_jobs] == ["2"]

    settled = run_company(
        _FakeScraper([[_job("1"), _job("2")]]), store=store, fetch_page=lambda c, u: "0"
    )
    assert settled.new_jobs == []


def test_record_run_appends_a_health_row(store):
    store.record_run("Acme", "ok", jobs_read=40, jobs_new=3)
    with psycopg.connect(TEST_DSN, autocommit=True) as conn:
        row = conn.execute(
            "SELECT status, jobs_read, jobs_new FROM company_runs WHERE company = %s",
            ("Acme",),
        ).fetchone()
    assert row == ("ok", 40, 3)
