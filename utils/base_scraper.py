"""Shared scraper infrastructure — pagination, rate limiting, checkpoint."""

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from utils.fingerprint import Deduplicator
from utils.rate_limiter import RateLimiter
from config import (
    SEARCH_KEYWORDS, SEARCH_CITIES, SEARCH_MODES,
    MAX_PAGES_PER_SEARCH, MAX_WORKERS, SCRAPE_CHECKPOINT,
    DUPLICATE_STOP_THRESHOLD,
)

log = logging.getLogger("agent")


class ScraperStats:
    """Tracks scraper performance statistics."""

    def __init__(self) -> None:
        self.queries: int = 0
        self.pages_scraped: int = 0
        self.jobs_found: int = 0
        self.duplicates: int = 0
        self.failed_requests: int = 0
        self.early_stopped: int = 0
        self.total_duration: float = 0.0
        self.search_durations: List[float] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "queries": self.queries,
            "pages_scraped": self.pages_scraped,
            "jobs_found": self.jobs_found,
            "duplicates": self.duplicates,
            "failed_requests": self.failed_requests,
            "early_stopped": self.early_stopped,
            "total_duration": round(self.total_duration, 2),
            "avg_duration": round(
                sum(self.search_durations) / len(self.search_durations), 2
            ) if self.search_durations else 0,
        }


class BaseScraper(ABC):
    """Base class for job scrapers with pagination, rate limiting, and checkpointing."""

    def __init__(self, name: str, stop_event: Optional[threading.Event] = None) -> None:
        self.name = name
        self.stop_event = stop_event
        self.stats = ScraperStats()
        self.dedup = Deduplicator()
        self.rate_limiter = RateLimiter()
        self.all_jobs: List[Dict[str, Any]] = []
        self.rejected_jobs: List[Dict[str, Any]] = []

    @abstractmethod
    def search_keyword(
        self,
        keyword: str,
        category: str,
        location: str,
        page: int,
        job_age_hours: int,
    ) -> List[Dict[str, Any]]:
        """Execute one search page. Override per platform."""
        ...

    @abstractmethod
    def transform_job(self, raw: Dict[str, Any], keyword: str, category: str) -> Dict[str, Any]:
        """Transform raw job data to standardised format."""
        ...

    def get_location_variants(self, keyword: str, category: str) -> List[str]:
        """Get all location/mode variants for a keyword."""
        variants = []
        for city in SEARCH_CITIES:
            variants.append((keyword, category, city, "onsite"))
        if SEARCH_MODES.get("remote", True):
            variants.append((keyword, category, "Remote", "remote"))
        if SEARCH_MODES.get("hybrid", True):
            for city in SEARCH_CITIES[:2]:
                variants.append((keyword, category, f"{city} (Hybrid)", "hybrid"))
        if SEARCH_MODES.get("work_from_home", True):
            variants.append((keyword, category, "Work From Home", "wfh"))
        if SEARCH_MODES.get("india_wide", True):
            variants.append((keyword, category, "All India", "india"))
        return variants

    def filter_blacklisted(self, jobs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Filter out blacklisted companies."""
        from config import BLACKLIST
        kept = []
        rejected = []
        blacklist_lower = [b.lower().strip() for b in BLACKLIST]
        for job in jobs:
            company = (job.get("company") or "").lower().strip()
            title = (job.get("title") or "").lower().strip()
            is_blacklisted = False
            for b in blacklist_lower:
                if b in company or b in title:
                    is_blacklisted = True
                    break
            if is_blacklisted:
                job["rejection_reason"] = f"Blacklisted company/keyword match"
                rejected.append(job)
            else:
                kept.append(job)
        return kept, rejected

    def search_all_variants(self, job_age_hours: int = 24) -> List[Dict[str, Any]]:
        """Search across all keywords, locations, and modes with pagination."""
        self._load_checkpoint()

        all_variants = []
        for keyword in SEARCH_KEYWORDS:
            category = self._infer_category(keyword)
            variants = self.get_location_variants(keyword, category)
            all_variants.extend(variants)

        combo_count = len(all_variants)
        log.info("  %s: %s search combos, %s pages each", self.name, combo_count, MAX_PAGES_PER_SEARCH)

        start_all = time.time()
        self.stats.total_duration = 0.0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for keyword, category, location, mode in all_variants:
                if self.stop_event and self.stop_event.is_set():
                    log.info("  %s: Early stop — target reached, skipping remaining variants", self.name)
                    break
                future = executor.submit(
                    self._search_single_variant, keyword, category, location, mode, job_age_hours
                )
                futures[future] = (keyword, location, mode)

            for future in as_completed(futures):
                if self.stop_event and self.stop_event.is_set():
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    break
                keyword, location, mode = futures[future]
                try:
                    jobs, duration = future.result()
                    self.stats.search_durations.append(duration)
                    self.stats.total_duration += duration

                    for job in jobs:
                        if self.dedup.is_duplicate(
                            job.get("company", ""),
                            job.get("title", ""),
                            job.get("location", ""),
                            job.get("url", ""),
                        ):
                            self.stats.duplicates += 1
                            continue
                        self.all_jobs.append(job)
                        self.stats.jobs_found += 1
                except Exception as e:
                    self.stats.failed_requests += 1
                    log.warning("  %s: Failed combo %s/%s: %s", self.name, keyword, location, e)

        clean, rejected_blacklist = self.filter_blacklisted(self.all_jobs)
        self.all_jobs = clean
        self.rejected_jobs.extend(rejected_blacklist)

        self.stats.total_duration = time.time() - start_all
        self._save_checkpoint()

        log.info(
            "%s: %s combos, %s jobs found, %s dups, %s failed, %.1fs",
            self.name, combo_count, self.stats.jobs_found,
            self.stats.duplicates, self.stats.failed_requests,
            self.stats.total_duration,
        )
        return self.all_jobs

    def _search_single_variant(
        self, keyword: str, category: str, location: str, mode: str, job_age_hours: int
    ) -> Tuple[List[Dict[str, Any]], float]:
        """Search a single keyword+location combo across pages."""
        start = time.time()
        all_jobs: List[Dict[str, Any]] = []
        seen_ids: set = set()

        for page in range(MAX_PAGES_PER_SEARCH):
            if self.stop_event and self.stop_event.is_set():
                break
            try:
                raw_jobs = self.search_keyword(keyword, category, location, page, job_age_hours)
            except Exception as e:
                log.debug("  %s: Error on page %s/%s: %s", self.name, page + 1, keyword, e)
                break

            if not raw_jobs:
                if page == 0:
                    log.debug("  %s: No results for '%s' at '%s'", self.name, keyword, location)
                break

            count_before = len(all_jobs)
            page_dups = 0
            for raw in raw_jobs:
                jid = raw.get("job_id", "")
                if jid and jid in seen_ids:
                    page_dups += 1
                    continue
                if jid:
                    seen_ids.add(jid)

                transformed = self.transform_job(raw, keyword, category)
                if mode == "remote":
                    transformed["location"] = "Remote"
                elif mode == "hybrid":
                    if "hybrid" not in (transformed.get("location", "") or "").lower():
                        transformed["location"] = f"{location.split('(')[0].strip()} (Hybrid)"
                elif mode == "wfh":
                    transformed["location"] = "Work From Home"
                all_jobs.append(transformed)

            self.stats.pages_scraped += 1

            if page > 0 and page_dups > 0:
                dup_ratio = page_dups / len(raw_jobs)
                if dup_ratio >= DUPLICATE_STOP_THRESHOLD:
                    self.stats.early_stopped += 1
                    log.debug("  %s: Early stop at page %s for '%s'/'%s'", self.name, page + 1, keyword, location)
                    break

        duration = time.time() - start
        log.debug("  %s: '%s' at '%s' -> %s jobs (%.1fs)", self.name, keyword, location, len(all_jobs), duration)
        return all_jobs, duration

    def _infer_category(self, keyword: str) -> str:
        """Infer job category from keyword."""
        kw = keyword.lower()
        if any(x in kw for x in ["data analyst", "business analyst", "business intelligence", "power bi", "sql", "analytics"]):
            return "data_analyst"
        if any(x in kw for x in ["financial", "fp&a", "finance", "accounts", "accountant", "sap"]):
            return "finance_roles"
        if any(x in kw for x in ["ai engineer", "machine learning", "ml engineer"]):
            return "agentic_ai"
        if any(x in kw for x in ["genai", "llm", "rag", "prompt", "generative"]):
            return "genai_llm"
        if any(x in kw for x in ["intern", "fresher"]):
            return "fresher_ai_ml"
        if any(x in kw for x in ["data scientist", "data engineer"]):
            return "agentic_ai"
        return "data_analyst"

    def _checkpoint_path(self) -> str:
        return SCRAPE_CHECKPOINT.replace(".json", f"_{self.name.lower()}.json")

    def _save_checkpoint(self) -> None:
        """Save progress to resume on failure."""
        data = {
            "jobs_found": len(self.all_jobs),
            "stats": self.stats.to_dict(),
            "rejected": len(self.rejected_jobs),
        }
        try:
            with open(self._checkpoint_path(), "w") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            log.warning("  %s: Checkpoint save failed: %s", self.name, e)

    def _load_checkpoint(self) -> None:
        """Load checkpoint if available (not used for resume, just status)."""
        path = self._checkpoint_path()
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                log.info("  %s: Previous checkpoint found: %s jobs", self.name, data.get("jobs_found", 0))
            except (json.JSONDecodeError, OSError):
                pass

    def get_stats(self) -> Dict[str, Any]:
        return self.stats.to_dict()
