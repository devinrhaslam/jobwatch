from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from jobwatch.models import Job

DEFAULT_STATE_DIR = Path("state")


def snapshot_path(company: str, state_dir: Path = DEFAULT_STATE_DIR) -> Path:
    safe_name = re.sub(r"[^a-z0-9_]+", "_", company.lower()).strip("_")
    return state_dir / f"{safe_name}.json"


def snapshot_exists(company: str, state_dir: Path = DEFAULT_STATE_DIR) -> bool:
    return snapshot_path(company, state_dir).exists()


def load_snapshot(company: str, state_dir: Path = DEFAULT_STATE_DIR) -> dict[str, dict]:
    path = snapshot_path(company, state_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_snapshot(
    company: str, snapshot: dict[str, dict], state_dir: Path = DEFAULT_STATE_DIR
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(company, state_dir)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")


def merge_snapshot(
    snapshot: dict[str, dict], jobs: list[Job], now: datetime | None = None
) -> dict[str, dict]:
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    merged = {job_id: dict(record) for job_id, record in snapshot.items()}
    for job in jobs:
        record = merged.get(job.job_id)
        if record is None:
            merged[job.job_id] = {**asdict(job), "first_seen": now_iso, "last_seen": now_iso}
        else:
            record.update(asdict(job))
            record["last_seen"] = now_iso
    return merged
