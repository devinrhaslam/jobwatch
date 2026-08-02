from datetime import datetime, timezone

import pytest

import jobwatch.state as state
from jobwatch.models import Job
from jobwatch.state import (
    load_snapshot,
    merge_snapshot,
    save_snapshot,
    snapshot_exists,
    snapshot_path,
)


def _job(job_id):
    return Job(
        company="Acme", job_id=job_id, title="Engineer", url=f"https://acme.example/{job_id}"
    )


def test_load_snapshot_missing_file_returns_empty_dict(tmp_path):
    assert load_snapshot("Acme", state_dir=tmp_path) == {}


def test_snapshot_exists_distinguishes_missing_and_empty_snapshots(tmp_path):
    assert not snapshot_exists("Acme", state_dir=tmp_path)

    save_snapshot("Acme", {}, state_dir=tmp_path)

    assert snapshot_exists("Acme", state_dir=tmp_path)


def test_save_and_load_snapshot_round_trip(tmp_path):
    save_snapshot("Acme", {"1": {"title": "Engineer"}}, state_dir=tmp_path)
    assert load_snapshot("Acme", state_dir=tmp_path) == {"1": {"title": "Engineer"}}


def test_snapshot_path_normalizes_company_name(tmp_path):
    path = snapshot_path("Hudson River Trading", state_dir=tmp_path)
    assert path == tmp_path / "hudson_river_trading.json"


def test_snapshot_path_preserves_existing_anthropic_mapping(tmp_path):
    path = snapshot_path("Anthropic", state_dir=tmp_path)
    assert path == tmp_path / "anthropic.json"


def test_snapshot_path_sanitizes_path_separators(tmp_path):
    path = snapshot_path("Evil/../Co", state_dir=tmp_path)
    assert path == tmp_path / "evil_co.json"
    assert path.resolve().is_relative_to(tmp_path.resolve())


def test_snapshot_path_sanitizes_punctuation(tmp_path):
    assert snapshot_path("Booking.com", state_dir=tmp_path) == tmp_path / "booking_com.json"
    assert snapshot_path("AT&T", state_dir=tmp_path) == tmp_path / "at_t.json"


def test_merge_snapshot_does_not_mutate_input_snapshot():
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    snapshot = merge_snapshot({}, [_job("1")], now=now)
    original = {job_id: dict(record) for job_id, record in snapshot.items()}
    merge_snapshot(snapshot, [_job("1"), _job("2")], now=now)
    assert snapshot == original


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


def test_save_snapshot_writes_valid_json_and_leaves_no_stray_temp_file(tmp_path):
    save_snapshot("Acme", {"1": {"title": "Engineer"}}, state_dir=tmp_path)

    assert load_snapshot("Acme", state_dir=tmp_path) == {"1": {"title": "Engineer"}}
    assert list(tmp_path.iterdir()) == [snapshot_path("Acme", tmp_path)]


def test_save_snapshot_failure_during_replace_leaves_existing_file_intact(
    tmp_path, monkeypatch
):
    save_snapshot("Acme", {"1": {"title": "Engineer"}}, state_dir=tmp_path)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(state.os, "replace", boom)

    with pytest.raises(OSError):
        save_snapshot("Acme", {"2": {"title": "New"}}, state_dir=tmp_path)

    assert load_snapshot("Acme", state_dir=tmp_path) == {"1": {"title": "Engineer"}}
    assert list(tmp_path.iterdir()) == [snapshot_path("Acme", tmp_path)]


def test_merge_snapshot_retains_departed_job():
    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    snapshot = merge_snapshot({}, [_job("1"), _job("2")], now=now)
    merged = merge_snapshot(snapshot, [_job("1")], now=now)
    assert "2" in merged
