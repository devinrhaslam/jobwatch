from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from jobwatch import state
from jobwatch.models import Job


class SnapshotStore(Protocol):
    """Persistence boundary for per-company job snapshots.

    The engine reads a company's known jobs through ``load`` — for the new-job
    diff and the suspicious-run ratio — and writes a run's scraped jobs back
    through ``save``, which owns the first_seen/last_seen merge. Keeping that
    merge inside the store is the whole point of this boundary: a SQL backend
    expresses it as an upsert that preserves first_seen, while the JSON backend
    expresses it in Python, and the engine calls the same two methods either
    way.
    """

    def exists(self, company: str) -> bool:
        """Whether this company has ever been persisted.

        Distinguishes a seed run (no snapshot yet) from a routine one, which is
        what decides whether an all-new read is expected or suspicious.
        """
        ...

    def load(self, company: str) -> dict[str, dict]:
        """Every job ever seen for this company, keyed by job_id.

        Each record is the job's fields plus first_seen/last_seen. Returns an
        empty dict when the company has never been persisted.
        """
        ...

    def save(self, company: str, jobs: list[Job], now: datetime | None = None) -> None:
        """Merge a run's scraped jobs into the stored snapshot.

        A job_id not yet stored is inserted with first_seen set to ``now``; one
        already stored keeps its first_seen and has its fields and last_seen
        refreshed. This is the write side of the honest-freshness property: a
        job is "new" exactly once — the first run that ever records its id.
        """
        ...

    def close(self) -> None:
        """Release any held resources; a no-op for file-backed stores."""
        ...


class JsonSnapshotStore:
    """SnapshotStore backed by one JSON file per company under a directory.

    A thin adapter over ``jobwatch.state``, which is the original on-disk
    format, so pre-database behaviour is preserved exactly. ``save`` reloads the
    snapshot rather than taking the one the engine already holds: the reload is
    a single cheap read per company per run, and keeping ``save`` self-contained
    means the interface never has to pass a snapshot that the SQL backend would
    only ignore.
    """

    def __init__(self, state_dir: Path = state.DEFAULT_STATE_DIR):
        self._state_dir = Path(state_dir)

    def exists(self, company: str) -> bool:
        return state.snapshot_exists(company, self._state_dir)

    def load(self, company: str) -> dict[str, dict]:
        return state.load_snapshot(company, self._state_dir)

    def save(self, company: str, jobs: list[Job], now: datetime | None = None) -> None:
        snapshot = state.load_snapshot(company, self._state_dir)
        merged = state.merge_snapshot(snapshot, jobs, now)
        state.save_snapshot(company, merged, self._state_dir)

    def close(self) -> None:
        pass


_UPSERT_SQL = """
INSERT INTO jobs (company, job_id, title, url, location, posted_date,
                  first_seen_at, last_seen_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (company, job_id) DO UPDATE SET
    title = EXCLUDED.title,
    url = EXCLUDED.url,
    location = EXCLUDED.location,
    posted_date = EXCLUDED.posted_date,
    last_seen_at = EXCLUDED.last_seen_at
"""


class PostgresSnapshotStore:
    """SnapshotStore backed by a Postgres ``jobs`` table.

    The merge that JsonSnapshotStore does in Python is an upsert here: an
    ``INSERT ... ON CONFLICT`` that preserves ``first_seen_at`` (it is not in the
    ``DO UPDATE SET`` list) and only refreshes the mutable fields and
    ``last_seen_at``. That is the honest-freshness property moved into the
    database, where it is expressed once and a second writer cannot race it.

    psycopg is imported lazily, so importing this module — and therefore the
    engine — never requires the driver for anyone still on the JSON store.
    """

    def __init__(self, dsn: str):
        import psycopg

        # autocommit so each statement is its own transaction; a board save is a
        # single executemany, which Postgres runs as one atomic statement, so the
        # whole board lands or none of it does — the same all-or-nothing the JSON
        # store gets from an atomic file replace.
        self._conn = psycopg.connect(dsn, autocommit=True)

    def close(self) -> None:
        self._conn.close()

    def exists(self, company: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("SELECT EXISTS (SELECT 1 FROM jobs WHERE company = %s)", (company,))
            return bool(cur.fetchone()[0])

    def load(self, company: str) -> dict[str, dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT job_id, company, title, url, location, posted_date, "
                "first_seen_at, last_seen_at FROM jobs WHERE company = %s",
                (company,),
            )
            rows = cur.fetchall()
        snapshot: dict[str, dict] = {}
        for job_id, comp, title, url, location, posted_date, first_seen, last_seen in rows:
            snapshot[job_id] = {
                "company": comp,
                "job_id": job_id,
                "title": title,
                "url": url,
                "location": location,
                "posted_date": posted_date,
                "first_seen": first_seen.isoformat(),
                "last_seen": last_seen.isoformat(),
            }
        return snapshot

    def save(self, company: str, jobs: list[Job], now: datetime | None = None) -> None:
        if not jobs:
            return
        now = now or datetime.now(timezone.utc)
        rows = [
            (job.company, job.job_id, job.title, job.url, job.location, job.posted_date, now, now)
            for job in jobs
        ]
        with self._conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, rows)

    def record_run(
        self,
        company: str,
        status: str,
        jobs_read: int = 0,
        jobs_new: int = 0,
        error: str | None = None,
    ) -> None:
        """Append a company's run outcome for the health view.

        Not yet called by run.py — that wiring lands with the ops dashboard — but
        it is the write side of ``company_runs`` and is tested here so the table
        is exercised, not vestigial.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO company_runs (company, status, jobs_read, jobs_new, error) "
                "VALUES (%s, %s, %s, %s, %s)",
                (company, status, jobs_read, jobs_new, error),
            )
