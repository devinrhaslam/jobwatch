# Task 6: Rendered Fetching Report

## Status

DONE: the browser environment blocker was resolved before final verification.
The full suite passes with real headless Chromium outside the sandbox.

## What I implemented

- Added `fetch_rendered(url, *, wait_for_selector=None, timeout_ms=30000,
  browser=None) -> str` to `jobwatch/fetch.py`.
- It opens a page with the existing `USER_AGENT`, navigates with
  `wait_until="networkidle"`, waits for the supplied selector (or 2 seconds
  when none is supplied), and returns the rendered DOM.
- It closes every page in a `finally` block, reuses a caller-supplied browser
  without closing it, and closes a browser it launches itself.
- Playwright failures from page creation, navigation, waiting, page closure,
  browser launch, browser closure, or Playwright-context teardown are
  normalized to `FetchError`.
- Added the prescribed local-only `http.server` fixture and two rendered-fetch
  tests. The server shuts down and its thread is joined in fixture teardown.

## TDD evidence

### RED

Command:

```bash
.venv/bin/pytest tests/test_fetch.py -v -k rendered
```

Result: collection failed with the expected
`ImportError: cannot import name 'fetch_rendered' from 'jobwatch.fetch'`.
This was expected because production code had not yet defined the new
function.

### GREEN

After the browser environment was restored, I ran:

```bash
.venv/bin/pytest
```

Result: 27 passed in 7.23 seconds. This exercised real Playwright Chromium
against the local loopback HTTP server; the rendered-success test verified
selector waiting, and the missing-selector test verified `FetchError`.

## Test results

- `.venv/bin/python -m py_compile jobwatch/fetch.py tests/test_fetch.py`:
  passed.
- `.venv/bin/pytest`: 27 passed in 7.23 seconds, with no warnings or stray
  output. This was run outside the sandbox as required for Chromium.
- IDE linter check for modified files: no errors.

## Files changed

- `jobwatch/fetch.py`
- `tests/test_fetch.py`
- `.superpowers/sdd/task-6-report.md`

## Self-review findings

- Page cleanup occurs in `finally`, including navigation and selector-wait
  failures; page-close failures are also normalized to `FetchError`.
- An externally supplied browser remains open; a locally launched browser is
  closed in `finally`, including when rendering fails.
- Raw Playwright lifecycle errors from page creation, navigation, waiting,
  browser launch, page close, browser close, and context teardown are
  translated to `FetchError`.
- The test fixture uses only a local loopback server and performs shutdown plus
  bounded thread join; no test contacts the public internet.
- `fetch_static` and its seven existing tests were not modified.

## Issues and concerns

- Browser-launching tests must be run outside the sandbox on this host because
  the sandboxed Playwright driver resolves the wrong CPU architecture. No
  source-level skip, environment detection, or test workaround was added.

---

# Task 6 Follow-up: Selector-wait Test Strengthening

## What changed

- Replaced the initially present `#ready` element in the local fixture page
  with JavaScript that appends it after 600 ms.
- The delayed element's complete text, `Delayed job listings loaded`, is
  assembled at runtime so it is absent from the initial HTML and script source.
- `test_fetch_rendered_waits_for_selector` now asserts that delayed text is in
  the returned HTML (and also asserts the static page-shell text). Capturing
  the DOM before the awaited selector appears would therefore fail.
- The missing-selector timeout test and loopback-only, deterministic server
  teardown remain unchanged. `fetch_static` and its seven tests were not
  modified.

## Evidence the test distinguishes an immediate capture

I used the same delayed local page with Playwright navigation ending at
`networkidle`, then called `page.content()` without `wait_for_selector`.
It exited 0 and printed:

```text
127.0.0.1 - - [01/Aug/2026 20:20:23] "GET /index.html HTTP/1.1" 200 -
Immediate capture omitted delayed content as expected
```

The command was run outside the sandbox:

```bash
env -u PLAYWRIGHT_BROWSERS_PATH .venv/bin/python -c $'import http.server\nimport tempfile\nimport threading\nfrom pathlib import Path\nfrom playwright.sync_api import sync_playwright\nhtml = """<!doctype html><html><body><div id="static-content">Page shell loaded</div><script>setTimeout(() => { const ready = document.createElement("div"); ready.id = "ready"; ready.textContent = ["Delayed", "job", "listings", "loaded"].join(" "); document.body.append(ready); }, 600);</script></body></html>"""\nwith tempfile.TemporaryDirectory() as directory:\n    Path(directory, "index.html").write_text(html, encoding="utf-8")\n    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=directory, **kwargs)\n    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)\n    thread = threading.Thread(target=server.serve_forever, daemon=True)\n    thread.start()\n    try:\n        with sync_playwright() as pw:\n            browser = pw.chromium.launch()\n            page = browser.new_page()\n            page.goto(f"http://127.0.0.1:{server.server_port}/index.html", wait_until="networkidle")\n            content = page.content()\n            browser.close()\n        assert "Delayed job listings loaded" not in content\n        print("Immediate capture omitted delayed content as expected")\n    finally:\n        server.shutdown()\n        thread.join(timeout=5)' 
```

## Verification

Full suite command, run outside the sandbox:

```bash
.venv/bin/pytest
```

Output:

```text
============================= test session starts ==============================
platform darwin -- Python 3.14.2, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/HMF4BGW/go/src/github.com/applications
configfile: pyproject.toml
collected 27 items

tests/test_diff.py ...                                                   [ 11%]
tests/test_fetch.py .........                                            [ 44%]
tests/test_models.py .....                                               [ 62%]
tests/test_state.py ..........                                           [100%]

============================== 27 passed in 7.31s ==============================
```

No implementation bug was found; `jobwatch/fetch.py` was not changed.

---

# Task 6 Follow-up: Required Selector and Timing Margin

## What changed

- The final signature is
  `fetch_rendered(url: str, *, wait_for_selector: str, timeout_ms: int = 30000, browser=None) -> str`.
  `wait_for_selector` is now a required keyword-only argument: omitting it raises
  Python's `TypeError` before browser launch. The fixed two-second fallback was
  removed entirely.
- I searched every repository reference to `fetch_rendered(`. The only current
  executable callers are the three tests in `tests/test_fetch.py`; the two
  existing rendered-fetch callers already provide a selector, and the added
  required-argument test intentionally omits it. References in
  `docs/superpowers/plans/2026-07-31-job-posting-watcher.md` are documentation,
  not callers.
- The local page now injects `#ready` after 1800 ms (previously 600 ms), leaving
  roughly 1.3 seconds beyond Playwright's ~500 ms network-idle window. The
  delayed-content assertion and never-appearing-selector `FetchError` test
  remain in place.

## Verification

The full suite was run outside the sandbox, with the stale Playwright browser
path cleared:

```bash
env -u PLAYWRIGHT_BROWSERS_PATH .venv/bin/pytest
```

Output:

```text
============================= test session starts ==============================
platform darwin -- Python 3.14.2, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/HMF4BGW/go/src/github.com/applications
configfile: pyproject.toml
collected 28 items

tests/test_diff.py ...                                                   [ 10%]
tests/test_fetch.py ..........                                           [ 46%]
tests/test_models.py .....                                               [ 64%]
tests/test_state.py ..........                                           [100%]

============================== 28 passed in 8.72s ==============================
```

The prior recorded full suite (27 tests) completed in 7.31s; this 28-test run
completed in 8.72s, a 1.41s increase. That is consistent with the 1.2s longer
selector delay plus normal run-to-run scheduling variation.
