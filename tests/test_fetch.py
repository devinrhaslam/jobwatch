import http.server
import threading

import requests

import pytest

from jobwatch.fetch import FetchBlocked, FetchError, fetch_rendered, fetch_static


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


def test_fetch_static_raises_fetch_error_on_404():
    session = _StubSession([_StubResponse(404)])
    with pytest.raises(FetchError):
        fetch_static("https://example.com", session=session)


def test_fetch_static_raises_fetch_error_after_retries_exhausted():
    session = _StubSession([_StubResponse(500), _StubResponse(500)])
    with pytest.raises(FetchError):
        fetch_static(
            "https://example.com", session=session, retries=2, backoff_seconds=0
        )


class _RaisingSession:
    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def get(self, url, timeout=None, headers=None):
        self.calls += 1
        raise self.exc


def test_fetch_static_exponential_backoff_on_5xx():
    delays = []

    def record_sleep(seconds):
        delays.append(seconds)

    session = _StubSession(
        [_StubResponse(500), _StubResponse(500), _StubResponse(500)]
    )
    with pytest.raises(FetchError):
        fetch_static(
            "https://example.com",
            session=session,
            retries=3,
            backoff_seconds=2.0,
            sleep=record_sleep,
        )
    assert delays == [2.0, 4.0]


def test_fetch_static_exponential_backoff_on_request_exception():
    delays = []

    def record_sleep(seconds):
        delays.append(seconds)

    session = _RaisingSession(requests.ConnectionError("connection reset"))
    with pytest.raises(FetchError):
        fetch_static(
            "https://example.com",
            session=session,
            retries=3,
            backoff_seconds=2.0,
            sleep=record_sleep,
        )
    assert delays == [2.0, 4.0]


def test_fetch_static_no_sleep_after_final_failed_attempt():
    delays = []

    def record_sleep(seconds):
        delays.append(seconds)

    session = _StubSession([_StubResponse(500)] * 4)
    with pytest.raises(FetchError):
        fetch_static(
            "https://example.com",
            session=session,
            retries=4,
            backoff_seconds=1.0,
            sleep=record_sleep,
        )
    assert len(delays) == 3


_LOCAL_HTML = """\
<!doctype html>
<html>
<body>
  <div id="static-content">Page shell loaded</div>
  <script>
    setTimeout(() => {
      const ready = document.createElement("div");
      ready.id = "ready";
      ready.textContent = ["Delayed", "job", "listings", "loaded"].join(" ");
      document.body.append(ready);
    }, 1800);
  </script>
</body>
</html>
"""


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
    assert "Page shell loaded" in html
    assert "Delayed job listings loaded" in html


def test_fetch_rendered_raises_on_missing_selector(local_server):
    with pytest.raises(FetchError):
        fetch_rendered(local_server, wait_for_selector="#does-not-exist", timeout_ms=3000)


def test_fetch_rendered_requires_wait_for_selector(local_server):
    with pytest.raises(TypeError, match="wait_for_selector"):
        fetch_rendered(local_server)


class _FakePage:
    def __init__(self, should_fail):
        self.should_fail = should_fail
        self.closed = False

    def goto(self, url, wait_until=None, timeout=None):
        if self.should_fail:
            raise TimeoutError("Timeout 30000ms exceeded")

    def wait_for_selector(self, selector, timeout=None):
        pass

    def content(self):
        return "<html>rendered</html>"

    def close(self):
        self.closed = True


class _FakeBrowser:
    """Stands in for a playwright Browser without launching real Chromium."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.pages: list[_FakePage] = []

    def new_page(self, user_agent=None):
        page = _FakePage(should_fail=self._outcomes.pop(0))
        self.pages.append(page)
        return page


def test_fetch_rendered_retries_transient_failure_then_succeeds():
    browser = _FakeBrowser([True, False])
    html = fetch_rendered(
        "https://example.com",
        wait_for_selector="#ready",
        browser=browser,
        retries=3,
        backoff_seconds=0,
    )
    assert html == "<html>rendered</html>"
    assert len(browser.pages) == 2
    assert all(page.closed for page in browser.pages)


def test_fetch_rendered_raises_fetch_error_after_retries_exhausted():
    browser = _FakeBrowser([True, True, True])
    with pytest.raises(FetchError):
        fetch_rendered(
            "https://example.com",
            wait_for_selector="#ready",
            browser=browser,
            retries=3,
            backoff_seconds=0,
        )
    assert len(browser.pages) == 3
    assert all(page.closed for page in browser.pages)


def test_fetch_rendered_no_sleep_after_final_failed_attempt():
    delays = []

    def record_sleep(seconds):
        delays.append(seconds)

    browser = _FakeBrowser([True, True, True, True])
    with pytest.raises(FetchError):
        fetch_rendered(
            "https://example.com",
            wait_for_selector="#ready",
            browser=browser,
            retries=4,
            backoff_seconds=1.0,
            sleep=record_sleep,
        )
    assert delays == [1.0, 2.0, 4.0]


# --- JSON_POST fetch -------------------------------------------------------


def test_build_and_split_post_url_round_trip():
    from jobwatch.fetch import build_post_url, split_post_url

    endpoint = "https://example.com/wday/cxs/acme/site/jobs"
    body = {"limit": 20, "offset": 40, "searchText": ""}
    url = build_post_url(endpoint, body)
    assert split_post_url(url) == (endpoint, body)


def test_split_post_url_defaults_to_an_empty_body():
    from jobwatch.fetch import split_post_url

    assert split_post_url("https://example.com/jobs") == ("https://example.com/jobs", {})


def test_split_post_url_rejects_an_unparseable_body():
    from jobwatch.fetch import FetchError, split_post_url

    with pytest.raises(FetchError, match="body parameter"):
        split_post_url("https://example.com/jobs?body=%7Bnot-json")


class _PostSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.posts = []

    def post(self, url, json=None, timeout=None, headers=None):
        self.posts.append((url, json))
        return self._responses.pop(0)


def test_fetch_json_post_sends_the_encoded_body_to_the_bare_endpoint():
    from jobwatch.fetch import build_post_url, fetch_json_post

    session = _PostSession([_StubResponse(200, text='{"jobPostings":[]}')])
    url = build_post_url("https://example.com/jobs", {"offset": 20})
    result = fetch_json_post(url, session=session)

    assert result == '{"jobPostings":[]}'
    assert session.posts == [("https://example.com/jobs", {"offset": 20})]


def test_fetch_json_post_raises_fetch_blocked_on_403():
    from jobwatch.fetch import FetchBlocked, fetch_json_post

    session = _PostSession([_StubResponse(403)])
    with pytest.raises(FetchBlocked):
        fetch_json_post("https://example.com/jobs", session=session)


def test_fetch_json_post_retries_on_500_then_succeeds():
    from jobwatch.fetch import fetch_json_post

    session = _PostSession([_StubResponse(500), _StubResponse(200, text="ok")])
    result = fetch_json_post(
        "https://example.com/jobs", session=session, retries=3, backoff_seconds=0
    )
    assert result == "ok"
    assert len(session.posts) == 2
