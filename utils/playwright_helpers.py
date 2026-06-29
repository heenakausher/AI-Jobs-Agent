"""Playwright-based headless browser helpers for sites that block direct HTTP."""

import logging
import time
from typing import Optional

log = logging.getLogger("agent")

_PLAYWRIGHT_AVAILABLE = None


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


def fetch_page_html(url: str, timeout_ms: int = 30000, wait_selector: Optional[str] = None) -> str:
    """Fetch page HTML using Playwright headless browser.

    Bypasses Cloudflare/anti-bot by using a real browser engine.
    Falls back to empty string if Playwright is not available.
    """
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
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            page = context.new_page()

            try:
                page.goto(url, wait_until="load", timeout=timeout_ms)
            except Exception as e:
                log.debug("Playwright goto timeout/error: %s", e)

            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=3000)
                except Exception:
                    pass

            time.sleep(1)
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        log.warning("Playwright fetch failed for %s: %s", url[:80], e)
        return ""
