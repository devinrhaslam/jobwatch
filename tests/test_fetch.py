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
