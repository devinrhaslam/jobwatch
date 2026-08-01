from datetime import datetime, timezone

from jobwatch.models import Job
from jobwatch.state import load_snapshot, merge_snapshot, save_snapshot, snapshot_path


def _job(job_id):
    return Job(
        company="Acme", job_id=job_id, title="Engineer", url=f"https://acme.example/{job_id}"
    )


def test_load_snapshot_missing_file_returns_empty_dict(tmp_path):
    assert load_snapshot("Acme", state_dir=tmp_path) == {}


def test_save_and_load_snapshot_round_trip(tmp_path):
    save_snapshot("Acme", {"1": {"title": "Engineer"}}, state_dir=tmp_path)
    assert load_snapshot("Acme", state_dir=tmp_path) == {"1": {"title": "Engineer"}}


def test_snapshot_path_normalizes_company_name(tmp_path):
    path = snapshot_path("Hudson River Trading", state_dir=tmp_path)
    assert path == tmp_path / "hudson_river_trading.json"


def test_merge_snapshot_adds_new_job_with_first_and_last_seen():
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    merged = merge_snapshot({}, [_job("1")], now=now)
    assert merged["1"]["first_seen"] == now.isoformat()
    assert merged["1"]["last_seen"] == now.isoformat()
    assert merged["1"]["title"] == "Engineer"


def test_merge_snapshot_updates_last_seen_but_keeps_first_seen():
    first = datetime(2026, 7, 30, tzinfo=timezone.utc)
    second = datetime(2026, 7, 31, tzinfo=timezone.utc)
    snapshot = merge_snapshot({}, [_job("1")], now=first)
    merged = merge_snapshot(snapshot, [_job("1")], now=second)
    assert merged["1"]["first_seen"] == first.isoformat()
    assert merged["1"]["last_seen"] == second.isoformat()


def test_merge_snapshot_retains_departed_job():
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    snapshot = merge_snapshot({}, [_job("1"), _job("2")], now=now)
    merged = merge_snapshot(snapshot, [_job("1")], now=now)
    assert "2" in merged
