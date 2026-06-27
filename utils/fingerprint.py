"""Fingerprint-based duplicate detection across platforms."""

import hashlib
import re
from typing import Dict, Optional


def normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, strip, remove extra spaces."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s]', '', text)
    return text.strip()


def make_fingerprint(
    company: str,
    title: str,
    location: str,
    url: str = "",
) -> str:
    """Create a stable fingerprint for a job.

    Uses company + title + location as primary key.
    Falls back to URL if available.
    """
    normalized = (
        normalize_text(company)[:50]
        + "|"
        + normalize_text(title)[:80]
        + "|"
        + normalize_text(location)[:50]
    )
    raw = normalized.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def make_url_fingerprint(url: str) -> str:
    """Create fingerprint from URL alone."""
    if not url:
        return ""
    raw = normalize_text(url).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class Deduplicator:
    """Cross-platform duplicate tracker using fingerprints."""

    def __init__(self) -> None:
        self._seen: Dict[str, bool] = {}
        self.duplicates_found: int = 0

    def is_duplicate(
        self,
        company: str,
        title: str,
        location: str,
        url: str = "",
    ) -> bool:
        fp = make_fingerprint(company, title, location)
        if fp in self._seen:
            self.duplicates_found += 1
            return True

        if url:
            url_fp = make_url_fingerprint(url)
            if url_fp and url_fp in self._seen:
                self.duplicates_found += 1
                return True
            self._seen[url_fp] = True

        self._seen[fp] = True
        return False

    def reset(self) -> None:
        self._seen.clear()
        self.duplicates_found = 0
