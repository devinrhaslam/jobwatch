from __future__ import annotations

import json
import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

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
    sleep: Callable[[float], None] = time.sleep,
    headers: dict[str, str] | None = None,
) -> str:
    session = session or requests.Session()
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=timeout, headers=request_headers)
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries - 1:
                sleep(backoff_seconds * (2**attempt))
            continue
        if response.status_code in (403, 429):
            raise FetchBlocked(f"{url} returned HTTP {response.status_code}")
        if response.status_code >= 500:
            last_error = FetchError(f"{url} returned HTTP {response.status_code}")
            if attempt < retries - 1:
                sleep(backoff_seconds * (2**attempt))
            continue
        if response.status_code >= 400:
            raise FetchError(f"{url} returned HTTP {response.status_code}")
        return response.text
    raise FetchError(f"failed to fetch {url} after {retries} attempts") from last_error


def split_post_url(url: str) -> tuple[str, dict]:
    """Split a JSON_POST page URL into its endpoint and request body.

    The framework identifies a page by its URL and paginates by handing back a
    new URL, but some boards only answer POST. Carrying the request body in a
    `body=` query parameter keeps a page addressable by URL — so pagination,
    logging, and error messages all keep working unchanged — while still
    letting the fetch layer send a real JSON body.
    """
    parsed = urlsplit(url)
    params = parse_qs(parsed.query)
    raw = params.pop("body", ["{}"])[0]
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FetchError(f"{url} has an unparseable body parameter: {exc}") from exc
    # Everything other than `body` belongs to the endpoint itself.
    endpoint = urlunsplit(
        parsed._replace(query=urlencode(params, doseq=True), fragment="")
    )
    return endpoint, body


def build_post_url(endpoint: str, body: dict) -> str:
    """Encode a POST body into a page URL, preserving any query the endpoint
    already carries.

    Naively appending `?body=...` produces a URL with two query strings when the
    endpoint has its own parameters, and the body then parses back as empty —
    silently sending a request with no parameters rather than failing.
    """
    parsed = urlsplit(endpoint)
    params = parse_qs(parsed.query)
    params["body"] = [json.dumps(body, sort_keys=True)]
    return urlunsplit(parsed._replace(query=urlencode(params, doseq=True)))


def fetch_json_post(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
    headers: dict[str, str] | None = None,
) -> str:
    """POST the body encoded in `url` and return the response text.

    Retry, blocked, and error semantics match fetch_static so a POST-only board
    behaves the same as every other company from the engine's point of view.
    """
    endpoint, body = split_post_url(url)
    session = session or requests.Session()
    request_headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        **(headers or {}),
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.post(
                endpoint, json=body, timeout=timeout, headers=request_headers
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries - 1:
                sleep(backoff_seconds * (2**attempt))
            continue
        if response.status_code in (403, 429):
            raise FetchBlocked(f"{endpoint} returned HTTP {response.status_code}")
        if response.status_code >= 500:
            last_error = FetchError(f"{endpoint} returned HTTP {response.status_code}")
            if attempt < retries - 1:
                sleep(backoff_seconds * (2**attempt))
            continue
        if response.status_code >= 400:
            raise FetchError(f"{endpoint} returned HTTP {response.status_code}")
        return response.text
    raise FetchError(f"failed to fetch {endpoint} after {retries} attempts") from last_error


def fetch_form_post(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
    headers: dict[str, str] | None = None,
) -> str:
    """Like fetch_json_post, but sends the body form-encoded.

    WordPress admin-ajax endpoints answer 400 to a JSON body, so the encoding
    is not interchangeable.
    """
    endpoint, body = split_post_url(url)
    session = session or requests.Session()
    request_headers = {
        "User-Agent": USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
        **(headers or {}),
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.post(
                endpoint, data=body, timeout=timeout, headers=request_headers
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries - 1:
                sleep(backoff_seconds * (2**attempt))
            continue
        if response.status_code in (403, 429):
            raise FetchBlocked(f"{endpoint} returned HTTP {response.status_code}")
        if response.status_code >= 500:
            last_error = FetchError(f"{endpoint} returned HTTP {response.status_code}")
            if attempt < retries - 1:
                sleep(backoff_seconds * (2**attempt))
            continue
        if response.status_code >= 400:
            raise FetchError(f"{endpoint} returned HTTP {response.status_code}")
        return response.text
    raise FetchError(f"failed to fetch {endpoint} after {retries} attempts") from last_error


def fetch_rendered_xhr(
    url: str,
    *,
    capture_response_url: str,
    engine: str = "chromium",
    timeout_ms: int = 45000,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    browser=None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Open `url` in a browser and return the body of the API call it makes.

    Some boards render entirely from one JSON call that carries the whole board.
    Reading that response gives the same data the page shows without depending
    on its markup, so a redesign of the page cannot break the parse.
    """
    from playwright.sync_api import sync_playwright

    def _render_once(pw_browser) -> str:
        # No user-agent override: the browser announces itself honestly. Pinning
        # the shared Chrome UA string here made a Firefox engine claim to be
        # Chrome, and a bot filter reads that mismatch as a disguise and blocks
        # the page — the opposite of the intent.
        page = pw_browser.new_page()
        try:
            # Arm the wait before navigating: the call fires during page load, so
            # registering afterwards would race it and time out on a fast page.
            with page.expect_response(
                lambda response: capture_response_url in response.url
                and response.status == 200,
                timeout=timeout_ms,
            ) as captured:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return captured.value.text()
        finally:
            page.close()

    def _fetch(pw_browser) -> str:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                return _render_once(pw_browser)
            except Exception as exc:
                last_error = exc
                if attempt < retries - 1:
                    sleep(backoff_seconds * (2**attempt))
        raise FetchError(
            f"failed to capture {capture_response_url} from {url} "
            f"after {retries} attempts"
        ) from last_error

    if browser is not None:
        return _fetch(browser)

    try:
        with sync_playwright() as pw:
            launched = getattr(pw, engine).launch()
            try:
                return _fetch(launched)
            finally:
                launched.close()
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"failed to render {url}: {exc}") from exc


def fetch_rendered(
    url: str,
    *,
    wait_for_selector: str,
    timeout_ms: int = 30000,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    browser=None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    from playwright.sync_api import sync_playwright

    def _render_once(pw_browser) -> str:
        page = pw_browser.new_page(user_agent=USER_AGENT)
        try:
            # domcontentloaded, not networkidle: the required wait_for_selector
            # below is the real readiness signal, and networkidle is flaky on
            # pages with analytics/polling that never go quiet.
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
            return page.content()
        finally:
            page.close()

    def _fetch(pw_browser) -> str:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                return _render_once(pw_browser)
            except Exception as exc:
                last_error = exc
                if attempt < retries - 1:
                    sleep(backoff_seconds * (2**attempt))
        raise FetchError(f"failed to render {url} after {retries} attempts") from last_error

    if browser is not None:
        return _fetch(browser)

    launched = None
    try:
        with sync_playwright() as pw:
            launched = pw.chromium.launch()
            try:
                return _fetch(launched)
            finally:
                launched.close()
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"failed to render {url}: {exc}") from exc
