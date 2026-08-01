# Job Posting Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that scrapes career pages for four pilot companies (Anthropic, Stripe, Cloudflare, Meta), diffs each run against a saved snapshot, and reports newly posted jobs to the console and a dated JSON log.

**Architecture:** One scraper class per company implements `parse(payload) -> list[Job]` and an optional `next_page_url`; a shared engine handles fetching (static HTTP or headless-browser rendering), pagination, snapshot diffing, and per-company error isolation. Role-fit filtering is a pass-through stub, applied at report time only, for phase 2 to fill in later.

**Tech Stack:** Python 3.11+, `requests`, `beautifulsoup4`, Playwright (Chromium) for JS-rendered pages, `pytest` for testing.

## Global Constraints

- Job source: scrape each company's actual career page — no third-party job aggregator APIs.
- Recency detection: snapshot diff (job IDs not seen before are new); a site's own posted date, when present, is stored as a secondary signal only, never the primary mechanism.
- Fetch strategy: hybrid — `requests` for static pages, Playwright/Chromium for JS-rendered pages, selected per company via `FetchMode`.
- Language: Python.
- Output: console report plus a dated JSON file under `output/`; no email/Slack/desktop notifications in this phase.
- Invocation: manual CLI only (`python run.py`); no scheduling (cron/launchd) in this phase.
- Snapshot state: one JSON file per company under `state/`, keyed by `job_id`, storing the full job record plus `first_seen` and `last_seen` timestamps. Departed jobs are never pruned.
- Zero-jobs regression guard: if a parse yields zero jobs against a non-empty snapshot, treat it as a failure and do not overwrite the snapshot.
- Suspicious-volume guard: if new jobs are ≥ 80% of a non-seed run's parsed jobs, flag the result as `suspicious` instead of reporting normally.
- Each company runs inside its own error boundary; one company failing must not stop the others.
- Role-fit filtering (seniority allow/deny lists) is out of scope for this plan; `filters.py` ships as a pass-through only.
- Scrapers beyond the four pilot companies are out of scope for this plan.
- Scheduled execution and additional notification channels are out of scope for this plan.

---

## File Structure

```
applications/
  requirements.txt
  pyproject.toml
  run.py
  conftest.py
  README.md
  jobwatch/
    __init__.py
    models.py
    state.py
    diff.py
    fetch.py
    engine.py
    report.py
    registry.py
    filters.py
    scrapers/
      __init__.py
      base.py
      anthropic.py
      stripe.py
      cloudflare.py
      meta.py
  tests/
    fixtures/
      anthropic_jobs.html        (already captured)
      stripe_jobs_search.html    (already captured)
      cloudflare_careers.html    (already captured)
      meta_jobsearch_page1.html  (already captured)
    test_models.py
    test_state.py
    test_diff.py
    test_fetch.py
    test_engine.py
    test_report.py
    test_scraper_anthropic.py
    test_scraper_stripe.py
    test_scraper_cloudflare.py
    test_scraper_meta.py
    test_registry.py
    test_filters.py
    test_run_cli.py
```

The four fixture files already exist at `tests/fixtures/` (captured during design recon) and are reused as-is; no task recreates them.

---

### Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `conftest.py`
- Create: `jobwatch/__init__.py`
- Create: `jobwatch/scrapers/__init__.py`

**Interfaces:**
- Produces: an importable `jobwatch` package (installed editable) and a `pytest` setup where `import jobwatch...` and top-level `import run` both work from any test file.

- [ ] **Step 1: Create `requirements.txt`**

```
beautifulsoup4>=4.12,<5
requests>=2.31,<3
playwright>=1.40,<2
pytest>=8.0,<9
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "jobwatch"
version = "0.1.0"
requires-python = ">=3.11"

[tool.setuptools]
packages = ["jobwatch", "jobwatch.scrapers"]
```

- [ ] **Step 3: Create empty package init files**

`jobwatch/__init__.py`:

```python
```

`jobwatch/scrapers/__init__.py`:

```python
```

- [ ] **Step 4: Create `conftest.py` at the repo root**

This guarantees the top-level `run.py` module is importable from tests regardless of how pytest computes its rootdir.

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
```

- [ ] **Step 5: Create the virtualenv and install dependencies**

Run:

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/pip install -e .
```

Expected: all commands exit 0. `playwright install chromium` downloads the headless browser used by rendered scrapers.

- [ ] **Step 6: Smoke-test pytest collection**

Run: `.venv/bin/pytest --collect-only`
Expected: reports `collected 0 items` / `no tests collected` with no collection errors, and exits 5 (pytest's documented `NO_TESTS_COLLECTED` code — not 0, since no test files exist yet). This confirms pytest starts and `jobwatch` imports cleanly.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pyproject.toml conftest.py jobwatch/__init__.py jobwatch/scrapers/__init__.py .gitignore
git commit -m "Scaffold jobwatch package and test setup"
```

---

### Task 2: Data Model

**Files:**
- Create: `jobwatch/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `FetchMode` (enum: `STATIC`, `RENDERED`), `Job` (dataclass: `company`, `job_id`, `title`, `url`, `location`, `posted_date`, plus `Job.stable_id(title, location, url) -> str` staticmethod), `CompanyConfig` (dataclass: `name`, `career_url`, `fetch_mode`, `wait_for_selector: str | None = None`).

**As implemented (review-driven addition):** `CompanyConfig.__post_init__` raises `ValueError` when `fetch_mode is FetchMode.RENDERED` and `wait_for_selector` is missing or empty, enforcing the spec's "required when RENDERED" rule rather than leaving it as a comment. Tasks 12 and 13 (the two RENDERED companies) already supply selectors, so this binds only future companies. Task 2 therefore ships 5 tests, not 3.

- [ ] **Step 1: Write the failing tests**

`tests/test_models.py`:

```python
from jobwatch.models import CompanyConfig, FetchMode, Job


def test_job_stable_id_is_deterministic():
    id1 = Job.stable_id("Software Engineer", "Remote", "https://acme.example/1")
    id2 = Job.stable_id("Software Engineer", "Remote", "https://acme.example/1")
    assert id1 == id2


def test_job_stable_id_differs_for_different_titles():
    id1 = Job.stable_id("Software Engineer", "Remote", "https://acme.example/1")
    id2 = Job.stable_id("Staff Software Engineer", "Remote", "https://acme.example/1")
    assert id1 != id2


def test_company_config_defaults_wait_for_selector_to_none():
    config = CompanyConfig(
        name="Acme", career_url="https://acme.example", fetch_mode=FetchMode.STATIC
    )
    assert config.wait_for_selector is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.models'`

- [ ] **Step 3: Write `jobwatch/models.py`**

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum


class FetchMode(Enum):
    STATIC = "static"
    RENDERED = "rendered"


@dataclass(frozen=True)
class Job:
    company: str
    job_id: str
    title: str
    url: str
    location: str | None = None
    posted_date: str | None = None  # ISO 8601 date string, e.g. "2026-07-31"

    @staticmethod
    def stable_id(title: str, location: str | None, url: str) -> str:
        raw = f"{title}|{location or ''}|{url}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class CompanyConfig:
    name: str
    career_url: str
    fetch_mode: FetchMode
    wait_for_selector: str | None = None  # required when fetch_mode is RENDERED
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/models.py tests/test_models.py
git commit -m "Add Job, CompanyConfig, and FetchMode data model"
```

---

### Task 3: Snapshot State

**Files:**
- Create: `jobwatch/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `Job` from `jobwatch.models` (Task 2).
- Produces: `snapshot_path(company, state_dir) -> Path`, `load_snapshot(company, state_dir) -> dict[str, dict]`, `save_snapshot(company, snapshot, state_dir) -> None`, `merge_snapshot(snapshot, jobs, now=None) -> dict[str, dict]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_state.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.state'`

- [ ] **Step 3: Write `jobwatch/state.py`**

```python
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from jobwatch.models import Job

DEFAULT_STATE_DIR = Path("state")


def snapshot_path(company: str, state_dir: Path = DEFAULT_STATE_DIR) -> Path:
    safe_name = company.lower().replace(" ", "_")
    return state_dir / f"{safe_name}.json"


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_state.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/state.py tests/test_state.py
git commit -m "Add per-company snapshot load/save/merge"
```

---

### Task 4: Job Diffing

**Files:**
- Create: `jobwatch/diff.py`
- Test: `tests/test_diff.py`

**Interfaces:**
- Consumes: `Job` from `jobwatch.models` (Task 2).
- Produces: `find_new_jobs(jobs: list[Job], snapshot: dict[str, dict]) -> list[Job]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_diff.py`:

```python
from jobwatch.diff import find_new_jobs
from jobwatch.models import Job


def _job(job_id, title="Software Engineer"):
    return Job(
        company="Acme", job_id=job_id, title=title, url=f"https://acme.example/{job_id}"
    )


def test_find_new_jobs_returns_only_unseen_ids():
    jobs = [_job("1"), _job("2"), _job("3")]
    snapshot = {"1": {}, "3": {}}
    new_jobs = find_new_jobs(jobs, snapshot)
    assert [j.job_id for j in new_jobs] == ["2"]


def test_find_new_jobs_empty_snapshot_returns_all():
    jobs = [_job("1"), _job("2")]
    assert find_new_jobs(jobs, {}) == jobs


def test_find_new_jobs_no_jobs_returns_empty():
    assert find_new_jobs([], {"1": {}}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_diff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.diff'`

- [ ] **Step 3: Write `jobwatch/diff.py`**

```python
from __future__ import annotations

from jobwatch.models import Job


def find_new_jobs(jobs: list[Job], snapshot: dict[str, dict]) -> list[Job]:
    return [job for job in jobs if job.job_id not in snapshot]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_diff.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/diff.py tests/test_diff.py
git commit -m "Add job diffing against saved snapshot"
```

---

### Task 5: Static Fetching

**Files:**
- Create: `jobwatch/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Produces: `FetchBlocked` (exception), `FetchError` (exception), `fetch_static(url, *, timeout=20, retries=3, backoff_seconds=2.0, session=None) -> str`.

This task covers only `fetch_static`; `fetch_rendered` is added in Task 6 in the same file.

- [ ] **Step 1: Write the failing tests**

`tests/test_fetch.py`:

```python
import requests

import pytest

from jobwatch.fetch import FetchBlocked, FetchError, fetch_static


class _StubResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _StubSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, timeout=None, headers=None):
        self.calls += 1
        return self._responses.pop(0)


def test_fetch_static_returns_text_on_200():
    session = _StubSession([_StubResponse(200, text="<html>ok</html>")])
    result = fetch_static("https://example.com", session=session)
    assert result == "<html>ok</html>"
    assert session.calls == 1


def test_fetch_static_raises_fetch_blocked_on_403():
    session = _StubSession([_StubResponse(403)])
    with pytest.raises(FetchBlocked):
        fetch_static("https://example.com", session=session)


def test_fetch_static_retries_on_500_then_succeeds():
    session = _StubSession([_StubResponse(500), _StubResponse(200, text="ok")])
    result = fetch_static(
        "https://example.com", session=session, retries=3, backoff_seconds=0
    )
    assert result == "ok"
    assert session.calls == 2


def test_fetch_static_raises_fetch_error_after_retries_exhausted():
    session = _StubSession([_StubResponse(500), _StubResponse(500)])
    with pytest.raises(FetchError):
        fetch_static(
            "https://example.com", session=session, retries=2, backoff_seconds=0
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.fetch'`

- [ ] **Step 3: Write `jobwatch/fetch.py` (static portion only)**

```python
from __future__ import annotations

import time

import requests

DEFAULT_TIMEOUT = 20
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 2.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class FetchBlocked(Exception):
    """Raised when a site returns 403/429, distinct from a real error."""


class FetchError(Exception):
    """Raised for any other fetch failure (timeout, connection, 5xx, etc.)."""


def fetch_static(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    session: requests.Session | None = None,
) -> str:
    session = session or requests.Session()
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(backoff_seconds * (attempt + 1))
            continue
        if response.status_code in (403, 429):
            raise FetchBlocked(f"{url} returned HTTP {response.status_code}")
        if response.status_code >= 500:
            last_error = FetchError(f"{url} returned HTTP {response.status_code}")
            time.sleep(backoff_seconds * (attempt + 1))
            continue
        response.raise_for_status()
        return response.text
    raise FetchError(f"failed to fetch {url} after {retries} attempts") from last_error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/fetch.py tests/test_fetch.py
git commit -m "Add fetch_static with retries and blocked detection"
```

---

### Task 6: Rendered Fetching

**Files:**
- Modify: `jobwatch/fetch.py` (add `fetch_rendered`)
- Modify: `tests/test_fetch.py` (add rendered-fetch tests)

**Interfaces:**
- Produces: `fetch_rendered(url, *, wait_for_selector=None, timeout_ms=30000, browser=None) -> str`, added to `jobwatch/fetch.py` alongside Task 5's exports.

This uses a local HTTP server serving a tiny synthetic page (not a real company fixture) so the test needs no external network access, only the already-installed local Playwright/Chromium.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fetch.py`:

```python
import http.server
import threading

from jobwatch.fetch import fetch_rendered

_LOCAL_HTML = "<!doctype html><html><body><div id=\"ready\">Loaded</div></body></html>"


@pytest.fixture
def local_server(tmp_path):
    (tmp_path / "index.html").write_text(_LOCAL_HTML, encoding="utf-8")

    def handler(*args, **kwargs):
        return http.server.SimpleHTTPRequestHandler(*args, directory=str(tmp_path), **kwargs)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_fetch_rendered_waits_for_selector(local_server):
    html = fetch_rendered(local_server, wait_for_selector="#ready", timeout_ms=10000)
    assert "Loaded" in html


def test_fetch_rendered_raises_on_missing_selector(local_server):
    with pytest.raises(FetchError):
        fetch_rendered(local_server, wait_for_selector="#does-not-exist", timeout_ms=3000)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_fetch.py -v -k rendered`
Expected: FAIL with `ImportError: cannot import name 'fetch_rendered'`

- [ ] **Step 3: Add `fetch_rendered` to `jobwatch/fetch.py`**

Append to `jobwatch/fetch.py`:

```python
def fetch_rendered(
    url: str,
    *,
    wait_for_selector: str | None = None,
    timeout_ms: int = 30000,
    browser=None,
) -> str:
    from playwright.sync_api import sync_playwright

    def _fetch(pw_browser) -> str:
        page = pw_browser.new_page(user_agent=USER_AGENT)
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            if wait_for_selector:
                page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
            else:
                page.wait_for_timeout(2000)
            return page.content()
        except Exception as exc:
            raise FetchError(f"failed to render {url}: {exc}") from exc
        finally:
            page.close()

    if browser is not None:
        return _fetch(browser)

    with sync_playwright() as pw:
        launched = pw.chromium.launch()
        try:
            return _fetch(launched)
        finally:
            launched.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_fetch.py -v`
Expected: PASS (6 tests total)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/fetch.py tests/test_fetch.py
git commit -m "Add fetch_rendered for JS-heavy career pages"
```

---

### Task 7: Scraper Base Class

**Files:**
- Create: `jobwatch/scrapers/base.py`
- Test: none (no behavior beyond what Tasks 10–13 exercise through concrete subclasses; an abstract class with no logic has nothing meaningful to unit test in isolation)

**Interfaces:**
- Consumes: `CompanyConfig`, `Job` from `jobwatch.models` (Task 2).
- Produces: `Scraper` (ABC) with abstract `parse(self, payload: str) -> list[Job]` and a concrete default `next_page_url(self, payload: str, current_url: str) -> str | None` returning `None`. Every concrete scraper (Tasks 10–13) sets a class attribute `config: CompanyConfig`.

- [ ] **Step 1: Write `jobwatch/scrapers/base.py`**

```python
from __future__ import annotations

from abc import ABC, abstractmethod

from jobwatch.models import CompanyConfig, Job


class Scraper(ABC):
    config: CompanyConfig

    @abstractmethod
    def parse(self, payload: str) -> list[Job]:
        ...

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        return None
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `.venv/bin/python -c "from jobwatch.scrapers.base import Scraper; print(Scraper)"`
Expected: prints `<class 'jobwatch.scrapers.base.Scraper'>` with no error.

- [ ] **Step 3: Commit**

```bash
git add jobwatch/scrapers/base.py
git commit -m "Add Scraper base class"
```

---

### Task 8: Run Orchestration Engine

**Files:**
- Create: `jobwatch/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `Job`, `CompanyConfig`, `FetchMode` from `jobwatch.models`; `find_new_jobs` from `jobwatch.diff`; `load_snapshot`, `save_snapshot`, `merge_snapshot` from `jobwatch.state`; `fetch_static`, `fetch_rendered`, `FetchBlocked`, `FetchError` from `jobwatch.fetch`; `Scraper` from `jobwatch.scrapers.base`.
- Produces: `CompanyResult` (dataclass: `company: str`, `status: str`, `new_jobs: list[Job]`, `total_jobs: int`, `detail: str | None = None`), `default_fetch_page(config, url, *, browser=None) -> str`, `run_company(scraper, *, state_dir, dry_run=False, fetch_page=default_fetch_page) -> CompanyResult`. `status` is one of `"seeded"`, `"ok"`, `"blocked"`, `"failed"`, `"suspicious"`. Task 9 (report) and Task 16 (CLI) both depend on these exact names.

- [ ] **Step 1: Write the failing tests**

`tests/test_engine.py`:

```python
from jobwatch.engine import run_company
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper
from jobwatch.state import load_snapshot


class FakeScraper(Scraper):
    """Pages are addressed by index; the fetch_page stub echoes/derives the
    index as the 'payload' so parse() and next_page_url() can stay pure."""

    def __init__(self, pages: list[list[Job]], config: CompanyConfig | None = None):
        self.config = config or CompanyConfig(
            name="Acme", career_url="0", fetch_mode=FetchMode.STATIC
        )
        self._pages = pages

    def parse(self, payload: str) -> list[Job]:
        return self._pages[int(payload)]

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        next_index = int(payload) + 1
        if next_index >= len(self._pages):
            return None
        return str(next_index)


def _job(job_id, title="Software Engineer"):
    return Job(
        company="Acme", job_id=job_id, title=title, url=f"https://acme.example/{job_id}"
    )


def test_first_run_seeds_without_reporting_new_jobs(tmp_path):
    scraper = FakeScraper([[_job("1"), _job("2")]])
    result = run_company(scraper, state_dir=tmp_path, fetch_page=lambda c, u: "0")
    assert result.status == "seeded"
    assert result.new_jobs == []
    assert result.total_jobs == 2


def test_unchanged_second_run_reports_no_new_jobs(tmp_path):
    scraper = FakeScraper([[_job("1"), _job("2")]])
    run_company(scraper, state_dir=tmp_path, fetch_page=lambda c, u: "0")
    result = run_company(scraper, state_dir=tmp_path, fetch_page=lambda c, u: "0")
    assert result.status == "ok"
    assert result.new_jobs == []


def test_genuinely_new_job_is_reported_once(tmp_path):
    run_company(
        FakeScraper([[_job("1")]]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    scraper_with_new_job = FakeScraper([[_job("1"), _job("2")]])
    result = run_company(
        scraper_with_new_job, state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    assert result.status == "ok"
    assert [j.job_id for j in result.new_jobs] == ["2"]

    result_again = run_company(
        scraper_with_new_job, state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    assert result_again.new_jobs == []


def test_departed_job_reappearing_is_not_reported_again(tmp_path):
    run_company(
        FakeScraper([[_job("1"), _job("2")]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: "0",
    )
    run_company(
        FakeScraper([[_job("1")]]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    result = run_company(
        FakeScraper([[_job("1"), _job("2")]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: "0",
    )
    assert result.new_jobs == []


def test_zero_jobs_against_nonempty_snapshot_fails_without_overwriting_state(tmp_path):
    run_company(
        FakeScraper([[_job("1"), _job("2")]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: "0",
    )
    result = run_company(
        FakeScraper([[]]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    assert result.status == "failed"
    assert set(load_snapshot("Acme", tmp_path)) == {"1", "2"}


def test_pagination_stops_early_when_page_has_no_new_ids(tmp_path):
    run_company(
        FakeScraper([[_job("1")], [_job("2")]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: u,
    )
    calls = []

    def counting_fetch(config, url):
        calls.append(url)
        return url

    result = run_company(
        FakeScraper([[_job("1")], [_job("2")]]),
        state_dir=tmp_path,
        fetch_page=counting_fetch,
    )
    assert calls == ["0"]
    assert result.new_jobs == []


def test_suspicious_ratio_flags_likely_id_scheme_change(tmp_path):
    run_company(
        FakeScraper([[_job(str(i)) for i in range(10)]]),
        state_dir=tmp_path,
        fetch_page=lambda c, u: "0",
    )
    mostly_new_jobs = [_job(str(i)) for i in range(2)] + [_job(f"new-{i}") for i in range(8)]
    result = run_company(
        FakeScraper([mostly_new_jobs]), state_dir=tmp_path, fetch_page=lambda c, u: "0"
    )
    assert result.status == "suspicious"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.engine'`

- [ ] **Step 3: Write `jobwatch/engine.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from jobwatch import diff, state
from jobwatch.fetch import FetchBlocked, FetchError, fetch_rendered, fetch_static
from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

MAX_PAGES = 20
SUSPICIOUS_NEW_JOB_RATIO = 0.8

FetchPage = Callable[[CompanyConfig, str], str]


def default_fetch_page(config: CompanyConfig, url: str, *, browser=None) -> str:
    if config.fetch_mode is FetchMode.STATIC:
        return fetch_static(url)
    return fetch_rendered(url, wait_for_selector=config.wait_for_selector, browser=browser)


@dataclass
class CompanyResult:
    company: str
    status: str
    new_jobs: list[Job]
    total_jobs: int
    detail: str | None = None


def run_company(
    scraper: Scraper,
    *,
    state_dir: Path,
    dry_run: bool = False,
    fetch_page: FetchPage = default_fetch_page,
) -> CompanyResult:
    config = scraper.config
    snapshot = state.load_snapshot(config.name, state_dir)
    is_seed_run = not snapshot

    try:
        jobs = _fetch_all_pages(
            scraper,
            config,
            known_ids=None if is_seed_run else set(snapshot),
            fetch_page=fetch_page,
        )
    except FetchBlocked as exc:
        return CompanyResult(config.name, "blocked", [], 0, str(exc))
    except FetchError as exc:
        return CompanyResult(config.name, "failed", [], 0, str(exc))

    if not jobs and snapshot:
        return CompanyResult(
            config.name,
            "failed",
            [],
            0,
            "parser returned zero jobs against a non-empty snapshot",
        )

    new_jobs = diff.find_new_jobs(jobs, snapshot)

    if not is_seed_run and jobs and len(new_jobs) / len(jobs) >= SUSPICIOUS_NEW_JOB_RATIO:
        return CompanyResult(
            config.name,
            "suspicious",
            new_jobs,
            len(jobs),
            f"{len(new_jobs)} of {len(jobs)} jobs are new; likely an ID/URL scheme change",
        )

    if not dry_run:
        merged = state.merge_snapshot(snapshot, jobs)
        state.save_snapshot(config.name, merged, state_dir)

    status = "seeded" if is_seed_run else "ok"
    reported_new = [] if is_seed_run else new_jobs
    return CompanyResult(config.name, status, reported_new, len(jobs))


def _fetch_all_pages(
    scraper: Scraper,
    config: CompanyConfig,
    *,
    known_ids: set[str] | None,
    fetch_page: FetchPage,
) -> list[Job]:
    all_jobs: dict[str, Job] = {}
    url = config.career_url
    for _ in range(MAX_PAGES):
        payload = fetch_page(config, url)
        page_jobs = scraper.parse(payload)
        page_has_new = False
        for job in page_jobs:
            all_jobs[job.job_id] = job
            if known_ids is None or job.job_id not in known_ids:
                page_has_new = True
        next_url = scraper.next_page_url(payload, url)
        if next_url is None:
            break
        if known_ids is not None and not page_has_new:
            break
        url = next_url
    return list(all_jobs.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_engine.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/engine.py tests/test_engine.py
git commit -m "Add run orchestration engine with pagination and failure guards"
```

---

### Task 9: Report Formatting & Output

**Files:**
- Create: `jobwatch/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `CompanyResult` from `jobwatch.engine` (Task 8); `Job` from `jobwatch.models`.
- Produces: `format_report(results: list[CompanyResult]) -> str`, `write_report(results: list[CompanyResult], output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path`.

- [ ] **Step 1: Write the failing tests**

`tests/test_report.py`:

```python
import json

from jobwatch.engine import CompanyResult
from jobwatch.models import Job
from jobwatch.report import format_report, write_report


def _job(job_id):
    return Job(
        company="Acme", job_id=job_id, title="Engineer", url=f"https://acme.example/{job_id}"
    )


def test_format_report_lists_new_jobs_with_links():
    results = [CompanyResult("Acme", "ok", [_job("1")], 5)]
    text = format_report(results)
    assert "Acme" in text
    assert "https://acme.example/1" in text


def test_format_report_shows_seeded_companies_without_alerts():
    results = [CompanyResult("Acme", "seeded", [], 40)]
    text = format_report(results)
    assert "seeded 40 jobs" in text


def test_format_report_surfaces_failures_prominently():
    results = [CompanyResult("Acme", "failed", [], 0, "parser returned zero jobs")]
    text = format_report(results)
    assert "FAILED" in text
    assert "parser returned zero jobs" in text


def test_write_report_creates_dated_json_file(tmp_path):
    results = [CompanyResult("Acme", "ok", [_job("1")], 5)]
    path = write_report(results, output_dir=tmp_path)
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload[0]["company"] == "Acme"
    assert payload[0]["new_jobs"][0]["job_id"] == "1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.report'`

- [ ] **Step 3: Write `jobwatch/report.py`**

```python
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from jobwatch.engine import CompanyResult

DEFAULT_OUTPUT_DIR = Path("output")


def format_report(results: list[CompanyResult]) -> str:
    total_new = sum(len(r.new_jobs) for r in results)
    lines = [f"Job Posting Watcher — {len(results)} companies, {total_new} new jobs", ""]
    for result in results:
        if result.status == "ok" and result.new_jobs:
            lines.append(f"## {result.company} — {len(result.new_jobs)} new")
            for job in result.new_jobs:
                loc = f" ({job.location})" if job.location else ""
                lines.append(f"  - {job.title}{loc}\n    {job.url}")
        elif result.status == "ok":
            lines.append(f"## {result.company} — no new jobs")
        elif result.status == "seeded":
            lines.append(f"## {result.company} — seeded {result.total_jobs} jobs, no alerts")
        elif result.status == "blocked":
            lines.append(f"## {result.company} — BLOCKED: {result.detail}")
        elif result.status == "failed":
            lines.append(f"## {result.company} — FAILED: {result.detail}")
        elif result.status == "suspicious":
            lines.append(f"## {result.company} — SUSPICIOUS: {result.detail}")
    return "\n".join(lines)


def write_report(
    results: list[CompanyResult], output_dir: Path = DEFAULT_OUTPUT_DIR
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{date.today().isoformat()}.json"
    payload = [
        {
            "company": r.company,
            "status": r.status,
            "total_jobs": r.total_jobs,
            "detail": r.detail,
            "new_jobs": [asdict(job) for job in r.new_jobs],
        }
        for r in results
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_report.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/report.py tests/test_report.py
git commit -m "Add console and JSON report output"
```

---

### Task 10: Anthropic Scraper

**Files:**
- Create: `jobwatch/scrapers/anthropic.py`
- Test: `tests/test_scraper_anthropic.py`
- Uses fixture: `tests/fixtures/anthropic_jobs.html` (already present)

**Interfaces:**
- Consumes: `Scraper` from `jobwatch.scrapers.base`; `CompanyConfig`, `FetchMode`, `Job` from `jobwatch.models`.
- Produces: `AnthropicScraper` (class), importable as `jobwatch.scrapers.anthropic.AnthropicScraper`, with `config.name == "Anthropic"`. Consumed by Task 14 (registry).

- [ ] **Step 1: Write the failing tests**

`tests/test_scraper_anthropic.py`:

```python
from pathlib import Path

from jobwatch.scrapers.anthropic import AnthropicScraper

FIXTURE = Path(__file__).parent / "fixtures" / "anthropic_jobs.html"


def test_parses_all_jobs_from_fixture():
    jobs = AnthropicScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(jobs) == 400
    assert len({j.job_id for j in jobs}) == 400


def test_parses_known_job_fields():
    jobs = AnthropicScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    job = next(j for j in jobs if j.job_id == "4980436008")
    assert "Research Manager" in job.title
    assert job.location == "San Francisco, CA"
    assert job.url == "https://job-boards.greenhouse.io/anthropic/jobs/4980436008"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_scraper_anthropic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.scrapers.anthropic'`

- [ ] **Step 3: Write `jobwatch/scrapers/anthropic.py`**

Anthropic's CSS classes are build-hashed and change on every deploy, so this parser keys off the href pattern and structural position (the anchor's first two `p.caption` descendants), never off class names.

```python
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

CONFIG = CompanyConfig(
    name="Anthropic",
    career_url="https://www.anthropic.com/jobs",
    fetch_mode=FetchMode.STATIC,
)


class AnthropicScraper(Scraper):
    config = CONFIG

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        jobs: list[Job] = []
        for anchor in soup.select('a[href*="/anthropic/jobs/"]'):
            href = anchor.get("href", "")
            match = re.search(r"/jobs/(\d+)", href)
            captions = anchor.select("p.caption")
            if not match or len(captions) < 2:
                continue
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=match.group(1),
                    title=captions[0].get_text(strip=True),
                    url=href,
                    location=captions[1].get_text(strip=True),
                )
            )
        return jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_scraper_anthropic.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/scrapers/anthropic.py tests/test_scraper_anthropic.py
git commit -m "Add Anthropic scraper"
```

---

### Task 11: Stripe Scraper

**Files:**
- Create: `jobwatch/scrapers/stripe.py`
- Test: `tests/test_scraper_stripe.py`
- Uses fixture: `tests/fixtures/stripe_jobs_search.html` (already present)

**Interfaces:**
- Consumes: `Scraper` from `jobwatch.scrapers.base`; `CompanyConfig`, `FetchMode`, `Job` from `jobwatch.models`.
- Produces: `StripeScraper` (class) with `config.name == "Stripe"`. Consumed by Task 14.

- [ ] **Step 1: Write the failing tests**

`tests/test_scraper_stripe.py`:

```python
from pathlib import Path

from jobwatch.scrapers.stripe import StripeScraper

FIXTURE = Path(__file__).parent / "fixtures" / "stripe_jobs_search.html"


def test_parses_all_jobs_from_embedded_json():
    jobs = StripeScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(jobs) == 513


def test_parses_known_job_fields():
    jobs = StripeScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    job = next(j for j in jobs if j.job_id == "8044460")
    assert job.title == "AI Engineer"
    assert job.url == "https://stripe.com/careers/listing/ai-engineer/8044460"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_scraper_stripe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.scrapers.stripe'`

- [ ] **Step 3: Write `jobwatch/scrapers/stripe.py`**

Stripe embeds a complete JSON payload of every listing directly in the page (no DOM scraping, no pagination needed). The `listings` array references a separate `locations` lookup table by index.

```python
from __future__ import annotations

import json

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

CONFIG = CompanyConfig(
    name="Stripe",
    career_url="https://stripe.com/jobs/search",
    fetch_mode=FetchMode.STATIC,
)


def _extract_json_array(payload: str, key: str) -> list[dict] | None:
    marker = f'"{key}":['
    index = payload.find(marker)
    if index == -1:
        return None
    start = payload.index("[", index)
    value, _ = json.JSONDecoder().raw_decode(payload, start)
    return value


class StripeScraper(Scraper):
    config = CONFIG

    def parse(self, payload: str) -> list[Job]:
        listings = _extract_json_array(payload, "listings")
        locations = _extract_json_array(payload, "locations") or []
        if not listings:
            return []
        jobs: list[Job] = []
        for listing in listings:
            job_id = listing.get("greenhouseId")
            title = listing.get("title")
            slug = listing.get("slug")
            if not (job_id and title and slug):
                continue
            location_names = [
                locations[i]["name"]
                for i in listing.get("locationIndices", [])
                if i < len(locations)
            ]
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=str(job_id),
                    title=title,
                    url=f"https://stripe.com/careers/listing/{slug}/{job_id}",
                    location=", ".join(location_names) or None,
                )
            )
        return jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_scraper_stripe.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/scrapers/stripe.py tests/test_scraper_stripe.py
git commit -m "Add Stripe scraper (embedded JSON payload)"
```

---

### Task 12: Cloudflare Scraper

**Files:**
- Create: `jobwatch/scrapers/cloudflare.py`
- Test: `tests/test_scraper_cloudflare.py`
- Uses fixture: `tests/fixtures/cloudflare_careers.html` (already present)

**Interfaces:**
- Consumes: `Scraper` from `jobwatch.scrapers.base`; `CompanyConfig`, `FetchMode`, `Job` from `jobwatch.models`.
- Produces: `CloudflareScraper` (class) with `config.name == "Cloudflare"`. Consumed by Task 14.

- [ ] **Step 1: Write the failing tests**

`tests/test_scraper_cloudflare.py`:

```python
from pathlib import Path

from jobwatch.scrapers.cloudflare import CloudflareScraper

FIXTURE = Path(__file__).parent / "fixtures" / "cloudflare_careers.html"


def test_deduplicates_jobs_rendered_twice():
    jobs = CloudflareScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(jobs) == 285
    assert len({j.job_id for j in jobs}) == 285


def test_parses_posted_date():
    jobs = CloudflareScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    job = next(j for j in jobs if j.job_id == "8099002")
    assert job.posted_date == "2026-07-31"
    assert job.location == "Sales - Chicago, US"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_scraper_cloudflare.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.scrapers.cloudflare'`

- [ ] **Step 3: Write `jobwatch/scrapers/cloudflare.py`**

Cloudflare's plain career page only renders 6 of 285 roles; the `#open-roles` fragment causes the full list to render into the DOM (verified stable across repeated loads). Each job appears twice in the rendered markup, so results are deduplicated by `job_id`.

```python
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

CONFIG = CompanyConfig(
    name="Cloudflare",
    career_url="https://www.cloudflare.com/careers/#open-roles",
    fetch_mode=FetchMode.RENDERED,
    wait_for_selector='a[href*="boards.greenhouse.io/cloudflare/jobs/"]',
)


def _parse_posted_date(text: str) -> str | None:
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


class CloudflareScraper(Scraper):
    config = CONFIG

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        by_id: dict[str, Job] = {}
        for anchor in soup.select('a[href*="boards.greenhouse.io/cloudflare/jobs/"]'):
            href = anchor.get("href", "")
            match = re.search(r"/jobs/(\d+)", href)
            paragraphs = [p.get_text(strip=True) for p in anchor.find_all("p")]
            if not match or len(paragraphs) < 2:
                continue
            job_id = match.group(1)
            if job_id in by_id:
                continue
            posted_date = None
            if len(paragraphs) >= 3:
                posted_match = re.match(r"^Posted\s+(.+)$", paragraphs[2])
                if posted_match:
                    posted_date = _parse_posted_date(posted_match.group(1))
            by_id[job_id] = Job(
                company=self.config.name,
                job_id=job_id,
                title=paragraphs[0],
                url=href,
                location=paragraphs[1],
                posted_date=posted_date,
            )
        return list(by_id.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_scraper_cloudflare.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/scrapers/cloudflare.py tests/test_scraper_cloudflare.py
git commit -m "Add Cloudflare scraper (rendered, #open-roles fragment)"
```

---

### Task 13: Meta Scraper

**Files:**
- Create: `jobwatch/scrapers/meta.py`
- Test: `tests/test_scraper_meta.py`
- Uses fixture: `tests/fixtures/meta_jobsearch_page1.html` (already present)

**Interfaces:**
- Consumes: `Scraper` from `jobwatch.scrapers.base`; `CompanyConfig`, `FetchMode`, `Job` from `jobwatch.models`.
- Produces: `MetaScraper` (class) with `config.name == "Meta"`, implementing `next_page_url`. Consumed by Task 14.

- [ ] **Step 1: Write the failing tests**

`tests/test_scraper_meta.py`:

```python
from pathlib import Path

from jobwatch.scrapers.meta import MetaScraper

FIXTURE = Path(__file__).parent / "fixtures" / "meta_jobsearch_page1.html"


def test_parses_jobs_from_fixture():
    jobs = MetaScraper().parse(FIXTURE.read_text(encoding="utf-8"))
    assert len(jobs) == 10
    assert all(j.job_id.isdigit() for j in jobs)


def test_next_page_url_increments_page_param():
    current = (
        "https://www.metacareers.com/jobsearch/"
        "?sort_by_new=true&teams[0]=Software+Engineering&page=1"
    )
    next_url = MetaScraper().next_page_url("<html></html>", current)
    assert "page=2" in next_url
    assert "teams[0]" in next_url


def test_next_page_url_returns_none_past_max_pages():
    current = "https://www.metacareers.com/jobsearch/?page=15"
    assert MetaScraper().next_page_url("<html></html>", current) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_scraper_meta.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.scrapers.meta'`

- [ ] **Step 3: Write `jobwatch/scrapers/meta.py`**

Meta rejects plain HTTP (returns 400) so it must run in `RENDERED` mode. Its unfiltered job list is far too large to enumerate page by page, so the entry URL applies Meta's own `teams[0]=Software Engineering` filter and `sort_by_new=true` sort — narrowing the crawl to relevant, newest-first results (verified: 10 jobs/page, zero overlap between pages).

```python
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from jobwatch.models import CompanyConfig, FetchMode, Job
from jobwatch.scrapers.base import Scraper

CONFIG = CompanyConfig(
    name="Meta",
    career_url=(
        "https://www.metacareers.com/jobsearch/"
        "?sort_by_new=true&teams[0]=Software%20Engineering&page=1"
    ),
    fetch_mode=FetchMode.RENDERED,
    wait_for_selector='a[href^="/profile/job_details/"]',
)

MAX_META_PAGES = 15


class MetaScraper(Scraper):
    config = CONFIG

    def parse(self, payload: str) -> list[Job]:
        soup = BeautifulSoup(payload, "html.parser")
        jobs: list[Job] = []
        for anchor in soup.select('a[href^="/profile/job_details/"]'):
            href = anchor.get("href", "")
            match = re.search(r"/profile/job_details/(\d+)", href)
            title_el = anchor.find("h3")
            if not match or title_el is None:
                continue
            title = title_el.get_text(strip=True)
            texts = list(anchor.stripped_strings)
            location = next((t for t in texts if t != title), None)
            jobs.append(
                Job(
                    company=self.config.name,
                    job_id=match.group(1),
                    title=title,
                    url=f"https://www.metacareers.com{href}",
                    location=location,
                )
            )
        return jobs

    def next_page_url(self, payload: str, current_url: str) -> str | None:
        parsed = urlparse(current_url)
        query = parse_qs(parsed.query)
        current_page = int(query.get("page", ["1"])[0])
        if current_page >= MAX_META_PAGES:
            return None
        query["page"] = [str(current_page + 1)]
        new_query = urlencode({k: v[0] for k, v in query.items()}, safe="[]")
        return urlunparse(parsed._replace(query=new_query))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_scraper_meta.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/scrapers/meta.py tests/test_scraper_meta.py
git commit -m "Add Meta scraper (rendered, filtered, paginated)"
```

---

### Task 14: Company Registry

**Files:**
- Create: `jobwatch/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `AnthropicScraper`, `StripeScraper`, `CloudflareScraper`, `MetaScraper` (Tasks 10–13); `Scraper` from `jobwatch.scrapers.base`.
- Produces: `SCRAPERS: dict[str, Scraper]`, `get_scraper(name: str) -> Scraper`. Consumed by Task 16 (CLI).

- [ ] **Step 1: Write the failing tests**

`tests/test_registry.py`:

```python
import pytest

from jobwatch.registry import SCRAPERS, get_scraper


def test_all_four_pilot_companies_registered():
    assert set(SCRAPERS) == {"Anthropic", "Stripe", "Cloudflare", "Meta"}


def test_get_scraper_returns_matching_scraper():
    scraper = get_scraper("Stripe")
    assert scraper.config.name == "Stripe"


def test_get_scraper_raises_with_available_list_on_unknown_name():
    with pytest.raises(KeyError, match="Anthropic"):
        get_scraper("Nonexistent Co")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.registry'`

- [ ] **Step 3: Write `jobwatch/registry.py`**

```python
from __future__ import annotations

from jobwatch.scrapers.anthropic import AnthropicScraper
from jobwatch.scrapers.base import Scraper
from jobwatch.scrapers.cloudflare import CloudflareScraper
from jobwatch.scrapers.meta import MetaScraper
from jobwatch.scrapers.stripe import StripeScraper

SCRAPERS: dict[str, Scraper] = {
    scraper.config.name: scraper
    for scraper in (
        AnthropicScraper(),
        StripeScraper(),
        CloudflareScraper(),
        MetaScraper(),
    )
}


def get_scraper(name: str) -> Scraper:
    try:
        return SCRAPERS[name]
    except KeyError as exc:
        available = ", ".join(sorted(SCRAPERS))
        raise KeyError(f"unknown company {name!r}; available: {available}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_registry.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/registry.py tests/test_registry.py
git commit -m "Add company registry"
```

---

### Task 15: Phase 2 Filter Stub

**Files:**
- Create: `jobwatch/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `Job` from `jobwatch.models`.
- Produces: `apply_filters(jobs: list[Job]) -> list[Job]`. Not yet called anywhere in this plan — wiring it into the report path is deferred to phase 2, per the spec.

- [ ] **Step 1: Write the failing test**

`tests/test_filters.py`:

```python
from jobwatch.filters import apply_filters
from jobwatch.models import Job


def test_apply_filters_is_currently_a_pass_through():
    jobs = [
        Job(company="Acme", job_id="1", title="Senior Software Engineer", url="https://x/1")
    ]
    assert apply_filters(jobs) == jobs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_filters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobwatch.filters'`

- [ ] **Step 3: Write `jobwatch/filters.py`**

```python
from __future__ import annotations

from jobwatch.models import Job


def apply_filters(jobs: list[Job]) -> list[Job]:
    """Phase 2 hook: role-fit filtering (seniority allow/deny lists) will be
    added here. It must stay a report-time filter — snapshots always store
    every job a company posts, regardless of fit, so widening this filter
    later does not lose history."""
    return list(jobs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_filters.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add jobwatch/filters.py tests/test_filters.py
git commit -m "Add pass-through filter stub for phase 2 role-fit filtering"
```

---

### Task 16: CLI Entrypoint

**Files:**
- Create: `run.py`
- Test: `tests/test_run_cli.py`

**Interfaces:**
- Consumes: `default_fetch_page`, `run_company` from `jobwatch.engine`; `FetchMode` from `jobwatch.models`; `SCRAPERS` from `jobwatch.registry`; `format_report`, `write_report` from `jobwatch.report`.
- Produces: `main(argv: list[str] | None = None) -> int`, plus module-level `SCRAPERS`, `STATE_DIR`, `OUTPUT_DIR`, `default_fetch_page` names that tests monkeypatch directly on the `run` module.

- [ ] **Step 1: Write the failing tests**

`tests/test_run_cli.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_run_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'run'`

- [ ] **Step 3: Write `run.py`**

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from jobwatch.engine import CompanyResult, default_fetch_page, run_company
from jobwatch.models import FetchMode
from jobwatch.registry import SCRAPERS
from jobwatch.report import format_report, write_report

STATE_DIR = Path("state")
OUTPUT_DIR = Path("output")


def _build_fetch_page(browser):
    def fetch_page(config, url):
        return default_fetch_page(config, url, browser=browser)

    return fetch_page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check tracked companies for newly posted jobs."
    )
    parser.add_argument(
        "--company",
        action="append",
        dest="companies",
        help="Limit the run to this company (repeatable). Defaults to all registered companies.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and report without writing snapshot state.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print per-company diagnostics to stderr."
    )
    args = parser.parse_args(argv)

    names = args.companies or sorted(SCRAPERS)
    unknown = [n for n in names if n not in SCRAPERS]
    if unknown:
        print(
            f"Unknown companies: {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(SCRAPERS))}",
            file=sys.stderr,
        )
        return 2

    needs_browser = any(SCRAPERS[n].config.fetch_mode is FetchMode.RENDERED for n in names)
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch() if needs_browser else None
        fetch_page = _build_fetch_page(browser)
        try:
            for name in names:
                scraper = SCRAPERS[name]
                if args.verbose:
                    print(f"Checking {name}...", file=sys.stderr)
                try:
                    result = run_company(
                        scraper,
                        state_dir=STATE_DIR,
                        dry_run=args.dry_run,
                        fetch_page=fetch_page,
                    )
                except Exception as exc:  # isolate one company's crash from the rest
                    result = CompanyResult(name, "failed", [], 0, f"unexpected error: {exc}")
                results.append(result)
        finally:
            if browser is not None:
                browser.close()

    print(format_report(results))
    if not args.dry_run:
        report_path = write_report(results, output_dir=OUTPUT_DIR)
        if args.verbose:
            print(f"\nWrote {report_path}", file=sys.stderr)

    return 1 if any(r.status in ("failed", "blocked") for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_run_cli.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add run.py tests/test_run_cli.py
git commit -m "Add CLI entrypoint"
```

---

### Task 17: Full Suite, Live Dry-Run, and README

**Files:**
- Create: `README.md`

**Interfaces:**
- None — this task verifies the assembled system and documents how to use it.

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/pytest -v`
Expected: PASS, 47 tests total (5 models + 6 state + 3 diff + 6 fetch + 7 engine + 4 report + 2 anthropic + 2 stripe + 2 cloudflare + 3 meta + 3 registry + 1 filters + 3 cli = 47), zero failures. If review-driven additions in earlier tasks changed a count, reconcile against the per-task expectations rather than assuming this total; what matters is zero failures and no skipped tests.

- [ ] **Step 2: Run a live dry-run against all four pilot companies**

Run: `.venv/bin/python run.py --dry-run --verbose`
Expected: exit code 0, a report section for each of Anthropic, Cloudflare, Meta, Stripe, each showing `seeded N jobs, no alerts` (since `state/` is empty on the first-ever run). Confirms the real network/Playwright path works end to end, not just fixture-backed unit tests. No files are written under `state/` because of `--dry-run`.

If any company reports `FAILED` or `BLOCKED` here, the corresponding scraper's selector needs revisiting against the live page before proceeding — do not skip this check.

- [ ] **Step 3: Run a real (non-dry-run) run to seed state**

Run: `.venv/bin/python run.py --verbose`
Expected: exit code 0, same `seeded` output as Step 2, and `state/anthropic.json`, `state/stripe.json`, `state/cloudflare.json`, `state/meta.json` now exist and are non-empty. `output/<today>.json` also exists.

- [ ] **Step 4: Run it again immediately to confirm zero false alerts**

Run: `.venv/bin/python run.py --verbose`
Expected: exit code 0, every company reports `no new jobs` (not `seeded` — state now exists from Step 3, and nothing changed on the live sites in the intervening seconds).

- [ ] **Step 5: Write `README.md`**

```markdown
# Job Posting Watcher

Checks a small set of company career pages for newly posted jobs and reports
what's new since the last run.

## Setup

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/playwright install chromium
    .venv/bin/pip install -e .

## Usage

    .venv/bin/python run.py                    # check all registered companies
    .venv/bin/python run.py --company Stripe    # check one company (repeatable)
    .venv/bin/python run.py --dry-run           # scrape and report, don't save state
    .venv/bin/python run.py --verbose           # print per-company progress

The first run for any company only seeds its snapshot — everything looks
"new" the first time, so nothing is reported as an alert until the second
run. Run it daily; each run reports jobs that weren't present last time.

## Currently tracked companies

Anthropic, Stripe, Cloudflare, Meta (software engineering roles only).

## Adding a company

1. Add a `CompanyConfig` and a `Scraper` subclass under `jobwatch/scrapers/`.
2. Register it in `jobwatch/registry.py`.
3. Capture a real page into `tests/fixtures/` and add a parser test.

## Project layout

- `jobwatch/engine.py` — fetch, diff, and save the snapshot for one company.
- `jobwatch/scrapers/` — one file per company; each implements `parse()`.
- `state/` — per-company snapshots of every job ID ever seen (gitignored).
- `output/` — one dated JSON report per run (gitignored).

## Known limitations

- Role-fit filtering (e.g. excluding Staff/Manager roles) is not implemented
  yet; `jobwatch/filters.py` is a pass-through stub for that future work.
- Only 4 of the companies in `companies.txt` have scrapers so far.
- No scheduling — run it manually.
```

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "Add README"
```

---

## Post-Plan Notes

- **Scaling to more companies:** each additional company is a new file under `jobwatch/scrapers/` plus one registry line and one fixture-backed test, following the pattern of Tasks 10–13. No other module changes.
- **Phase 2 (role filtering):** wire `jobwatch/filters.py` into `run.py` right before `format_report`/`write_report` are called, filtering `result.new_jobs` per company. Because state always stores every job regardless of filter, widening the filter later requires no snapshot changes or re-seeding.
