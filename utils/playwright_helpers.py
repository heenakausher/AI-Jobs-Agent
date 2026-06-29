"""Playwright-based headless browser helpers with HTTP fallback."""

import gzip
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

log = logging.getLogger("agent")

_PLAYWRIGHT_AVAILABLE = None

# Common desktop browser headers for HTTP fallback
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _check_playwright() -> bool:
    global _PLAYWRIGHT_AVAILABLE
    if _PLAYWRIGHT_AVAILABLE is not None:
        return _PLAYWRIGHT_AVAILABLE
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        _PLAYWRIGHT_AVAILABLE = True
    except Exception as e:
        log.warning("Playwright not available: %s", e)
        _PLAYWRIGHT_AVAILABLE = False
    return _PLAYWRIGHT_AVAILABLE


def _fetch_http(url: str, timeout_secs: int = 30) -> str:
    """Direct HTTP GET with browser-like headers and gzip handling."""
    try:
        req = urllib.request.Request(url, headers=_HTTP_HEADERS)
        resp = urllib.request.urlopen(req, timeout=timeout_secs)
        raw = resp.read()
        if raw[:2] == b'\x1f\x8b':
            raw = gzip.decompress(raw)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        log.debug("HTTP %s for %s", e.code, url[:80])
        return ""
    except Exception as e:
        log.debug("HTTP fetch failed for %s: %s", url[:80], e)
        return ""


def _fetch_playwright(url: str, timeout_ms: int, wait_selector: Optional[str]) -> str:
    """Fetch page HTML using Playwright headless browser."""
    if not _check_playwright():
        return ""

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                user_agent=_HTTP_HEADERS["User-Agent"],
                locale="en-US",
            )
            page = context.new_page()

            try:
                page.goto(url, wait_until="load", timeout=timeout_ms)
            except Exception as e:
                log.debug("Playwright goto timeout/error: %s", e)

            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=15000)
                except Exception:
                    pass

            time.sleep(1)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        log.warning("Playwright fetch failed for %s: %s", url[:80], e)
        return ""


def fetch_page_html(url: str, timeout_ms: int = 30000, wait_selector: Optional[str] = None) -> str:
    """Fetch page HTML — tries Playwright first, falls back to direct HTTP.

    Playwright bypasses Cloudflare/anti-bot using a real browser engine.
    HTTP fallback handles sites that serve server-rendered HTML.
    """
    html = _fetch_playwright(url, timeout_ms, wait_selector)
    if html:
        return html
    log.debug("Playwright returned empty for %s, trying HTTP fallback", url[:80])
    return _fetch_http(url, timeout_secs=max(1, timeout_ms // 1000))
