from __future__ import annotations

from datetime import datetime
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
