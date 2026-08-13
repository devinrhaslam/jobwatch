"""Import existing per-company JSON snapshots into the Postgres ``jobs`` table.

A one-time migration off the pre-database format. Each JSON record already
carries its own ``first_seen``/``last_seen`` — set when the job was first
seeded — so those are carried across verbatim rather than flattened to a single
backfill timestamp. That is both more honest (a job keeps the day it actually
appeared) and enough to satisfy the property that matters after a cutover:
every id already recorded exists in ``jobs``, so the next ingest reports none of
them as new.

Re-runnable: ``ON CONFLICT DO NOTHING`` means a second run never clobbers rows a
live ingest has since written.

Usage:
    JOBWATCH_DATABASE_URL=postgresql://jobwatch:jobwatch@localhost:5432/jobwatch \\
        python tools/migrate_json_to_postgres.py [--state-dir state]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

# Used only for a record missing its own first_seen/last_seen, which the current
# format never produces — a deliberately old date so such a row can never look
# like today's posting.
FALLBACK_TIMESTAMP = datetime(2020, 1, 1, tzinfo=timezone.utc)

_INSERT_SQL = """
INSERT INTO jobs (company, job_id, title, url, location, posted_date,
                  first_seen_at, last_seen_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (company, job_id) DO NOTHING
"""


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return FALLBACK_TIMESTAMP
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return FALLBACK_TIMESTAMP


def _rows_from_snapshot(snapshot: dict[str, dict]) -> list[tuple]:
    rows = []
    for job_id, record in snapshot.items():
        rows.append(
            (
                record["company"],
                job_id,
                record["title"],
                record["url"],
                record.get("location"),
                record.get("posted_date"),
                _parse_ts(record.get("first_seen")),
                _parse_ts(record.get("last_seen")),
            )
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="state", type=Path)
    parser.add_argument(
        "--dsn",
        default=os.environ.get("JOBWATCH_DATABASE_URL") or os.environ.get("DATABASE_URL"),
        help="Postgres DSN; defaults to $JOBWATCH_DATABASE_URL, then $DATABASE_URL.",
    )
    args = parser.parse_args(argv)

    if not args.dsn:
        print("No DSN: pass --dsn or set DATABASE_URL", file=sys.stderr)
        return 2

    files = sorted(args.state_dir.glob("*.json"))
    # The role-fit verdict cache lives alongside the snapshots but is not one.
    files = [f for f in files if f.name != "filter_cache.json"]
    if not files:
        print(f"No snapshot files under {args.state_dir}", file=sys.stderr)
        return 1

    rows: list[tuple] = []
    for path in files:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(_rows_from_snapshot(snapshot))

    with psycopg.connect(args.dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.executemany(_INSERT_SQL, rows)
        inserted = conn.execute("SELECT count(*) FROM jobs").fetchone()[0]

    print(
        f"Imported {len(rows)} job records from {len(files)} companies; "
        f"jobs table now holds {inserted} rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
