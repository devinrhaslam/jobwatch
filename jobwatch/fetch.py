from __future__ import annotations

import time
from collections.abc import Callable

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
) -> str:
    session = session or requests.Session()
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
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
        response.raise_for_status()
        return response.text
    raise FetchError(f"failed to fetch {url} after {retries} attempts") from last_error


def fetch_rendered(
    url: str,
    *,
    wait_for_selector: str | None = None,
    timeout_ms: int = 30000,
    browser=None,
) -> str:
    from playwright.sync_api import sync_playwright

    def _fetch(pw_browser) -> str:
        page = None
        failure = None
        try:
            page = pw_browser.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            if wait_for_selector:
                page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
            else:
                page.wait_for_timeout(2000)
            return page.content()
        except Exception as exc:
            failure = exc
            raise FetchError(f"failed to render {url}: {exc}") from exc
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception as exc:
                    if failure is None:
                        raise FetchError(f"failed to render {url}: {exc}") from exc

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
