"""Naukri.com scraper with pagination, per-keyword search, and rate limiting."""

import datetime
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from config import REQUEST_TIMEOUT
from utils.base_scraper import BaseScraper

log = logging.getLogger("agent")

NAUKRI_API = "https://www.naukri.com/jobapi/v3/search"

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "appid": "109",
    "systemid": "109",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.naukri.com/",
}


class NaukriScraper(BaseScraper):
    """Naukri.com job scraper."""

    def __init__(self) -> None:
        super().__init__("Naukri")

    def search_keyword(
        self,
        keyword: str,
        category: str,
        location: str,
        page: int,
        job_age_hours: int,
    ) -> List[Dict[str, Any]]:
        self.rate_limiter.wait()

        params = {
            "searchType": "adv",
            "keyword": keyword,
            "location": location,
            "pageNo": page + 1,
            "experienceType": "all",
            "jobAge": str(max(1, job_age_hours // 24)),
        }
        url = f"{NAUKRI_API}?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url, headers=BASE_HEADERS)
            resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
            data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                time.sleep(5)
                return []
            log.warning("  Naukri HTTP %s for %s/%s page %s", e.code, keyword, location, page + 1)
            return []
        except Exception as e:
            log.debug("  Naukri error %s/%s page %s: %s", keyword, location, page + 1, e)
            return []

        raw_jobs = data.get("jobDetails", [])
        if not raw_jobs:
            return []
        return raw_jobs

    def transform_job(self, raw: Dict[str, Any], keyword: str, category: str) -> Dict[str, Any]:
        title = (raw.get("title") or "").strip()
        company = (raw.get("companyName") or "").strip()
        location = self._extract_location(raw.get("placeholders") or [])
        job_id = raw.get("jdid") or raw.get("jobId", "")
        description = (raw.get("jobDescription") or raw.get("description", "")).strip()
        date_str = datetime.date.today().isoformat()

        url = f"https://www.naukri.com/job-details/{job_id}" if job_id else ""

        return {
            "category": category,
            "title": title,
            "company": company,
            "location": location,
            "date": date_str,
            "job_id": job_id,
            "description": description,
            "url": url,
            "source": "Naukri",
            "keyword": keyword,
        }

    def _extract_location(self, placeholders: list) -> str:
        if not placeholders:
            return "Hyderabad, India"
        for p in placeholders:
            label = (p.get("label") or "").strip()
            if label and "experience" not in label.lower():
                return label
        return placeholders[0].get("label", "Hyderabad, India")


def fetch_all(job_age_hours: int = 24) -> List[Dict[str, Any]]:
    scraper = NaukriScraper()
    return scraper.search_all_variants(job_age_hours=job_age_hours)


def get_last_stats() -> dict:
    return {}


def save_jobs(jobs: list, path: str = "naukri_jobs.json") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)


ALL_ROLES_FILE = "processed_jobs.json"


def merge_into_all_roles(naukri_jobs: list, all_roles_path: str = ALL_ROLES_FILE) -> int:
    if os.path.exists(all_roles_path):
        with open(all_roles_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = []

    existing_by_id = {}
    existing_by_key = {}
    for job in existing:
        jid = job.get("job_id", "")
        if jid:
            existing_by_id[jid] = job
        key = (job.get("title", ""), job.get("company", ""), job.get("location", ""))
        existing_by_key[key] = job

    new_count = 0
    for job in naukri_jobs:
        jid = job.get("job_id", "")
        key = (job.get("title", ""), job.get("company", ""), job.get("location", ""))
        if jid and jid in existing_by_id:
            continue
        if key in existing_by_key:
            continue
        out = {k: v for k, v in job.items() if not k.startswith("_")}
        existing.append(out)
        if jid:
            existing_by_id[jid] = out
        existing_by_key[key] = out
        new_count += 1

    with open(all_roles_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    return new_count
