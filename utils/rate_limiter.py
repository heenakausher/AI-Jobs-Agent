"""Rate limiter with random delays and user-agent rotation."""

import random
import time
import threading


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]


class RateLimiter:
    """Rate limiter with jitter and random user-agent selection."""

    def __init__(self, min_delay: float = 2.0, max_delay: float = 7.0) -> None:
        self._min = min_delay
        self._max = max_delay
        self._last_request: float = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Wait a random duration and update last request time."""
        delay = random.uniform(self._min, self._max)
        with self._lock:
            elapsed = time.time() - self._last_request
            if elapsed < delay:
                time.sleep(delay - elapsed)
            self._last_request = time.time()

    def get_random_headers(self) -> dict:
        """Return headers with a random user-agent."""
        ua = random.choice(USER_AGENTS)
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
        }
