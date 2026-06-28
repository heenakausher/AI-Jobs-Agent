"""LinkedIn scraper with pagination, per-keyword search, and rate limiting."""

import datetime
import gzip
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

LINKEDIN_BASE = "https://www.linkedin.com"
TIME_FILTERS = {24: "r86400"}


class LinkedInScraper(BaseScraper):
    """LinkedIn job scraper."""

    def __init__(self) -> None:
        super().__init__("LinkedIn")

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
            "keywords": keyword,
            "location": location,
            "start": str(page * 10),
        }
        # Closest LinkedIn time filter
        tpr = TIME_FILTERS.get(job_age_hours, "r86400")
        params["f_TPR"] = tpr
        # Filter by past 24 hours
        params["f_TPR"] = "r86400"

        url = f"{LINKEDIN_BASE}/jobs-guest/jobs/api/seeMoreJobPostings/search?{urllib.parse.urlencode(params)}"

        html = self._fetch_html(url)
        if not html:
            return []

        jobs = []
        for match in re.finditer(
            r'<div class="base-card[^>]*job-search-card[^>]*"(.*?)</div>\s*</li>',
            html, re.DOTALL,
        ):
            card_html = match.group(0)
            try:
                job = self._parse_card(card_html, keyword, location)
                if job:
                    jobs.append(job)
            except Exception:
                continue
        return jobs

    def transform_job(self, raw: Dict[str, Any], keyword: str, category: str) -> Dict[str, Any]:
        title = raw.get("title", "Unknown Position")
        company = raw.get("company", "Unknown Company")
        location = raw.get("location", "India")
        job_id = raw.get("job_id", "")
        description = raw.get("description", "")
        url = raw.get("url", "")

        clean_id = job_id.replace("linkedin_", "") if job_id else ""
        if clean_id and clean_id.isdigit() and not description:
            description = self._fetch_description(clean_id)
            time.sleep(1.5)

        date_str = datetime.date.today().isoformat()

        return {
            "category": category,
            "title": title,
            "company": company,
            "location": location,
            "date": date_str,
            "job_id": job_id,
            "description": description,
            "url": url,
            "source": "LinkedIn",
            "keyword": keyword,
        }

    def _fetch_html(self, url: str) -> str:
        headers = self.rate_limiter.get_random_headers()
        try:
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
            raw = resp.read()
            # Handle gzipped responses
            if raw[:2] == b'\x1f\x8b':
                raw = gzip.decompress(raw)
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                time.sleep(5)
            return ""
        except Exception:
            return ""

    def _parse_card(self, html: str, keyword: str, location: str) -> dict:
        job_id = ""
        m = re.search(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
        if m:
            job_id = m.group(1)
        if not job_id:
            m = re.search(r'/jobs/view/(\d+)', html)
            if m:
                job_id = m.group(1)

        title = ""
        m = re.search(r'<h3 class="base-search-card__title">\s*(.*?)\s*</h3>', html, re.DOTALL)
        if m:
            title = self._clean_html(m.group(1))

        company = ""
        m = re.search(
            r'<h4 class="base-search-card__subtitle">.*?<a[^>]*>\s*(.*?)\s*</a>',
            html, re.DOTALL,
        )
        if m:
            company = self._clean_html(m.group(1))

        loc = location
        m = re.search(r'<span class="job-search-card__location">\s*(.*?)\s*</span>', html, re.DOTALL)
        if m:
            loc = self._clean_html(m.group(1))

        job_url = ""
        m = re.search(r'<a class="base-card__full-link[^"]*" href="([^"]+)"', html)
        if m:
            job_url = m.group(1)

        if not title and not job_id:
            return {}

        return {
            "title": title or "Unknown Position",
            "company": company or "Unknown Company",
            "location": loc,
            "job_id": f"linkedin_{job_id}" if job_id else f"linkedin_{keyword}_{company}".replace(" ", "_"),
            "description": "",
            "keyword": keyword,
            "url": job_url,
        }

    def _fetch_description(self, job_id: str) -> str:
        if not job_id or not job_id.isdigit():
            return ""
        url = f"{LINKEDIN_BASE}/jobs-guest/jobs/api/jobPosting/{job_id}"
        html = self._fetch_html(url)
        if not html:
            return ""

        m = re.search(r'<section[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</section>', html, re.DOTALL)
        if m:
            desc = self._clean_html(m.group(1))
            if len(desc) > 50:
                return desc

        m = re.search(r'<div[^>]*class="[^"]*show-more-less-html[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
        if m:
            desc = self._clean_html(m.group(1))
            if len(desc) > 50:
                return desc
        return ""

    def _clean_html(self, text: str) -> str:
        text = re.sub(r'<[^>]+>', ' ', text)
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
        text = re.sub(r'\s+', ' ', text).strip()
        return text


def fetch_all(job_age_hours: int = 24) -> List[Dict[str, Any]]:
    scraper = LinkedInScraper()
    return scraper.search_all_variants(job_age_hours=job_age_hours)


def get_last_stats() -> dict:
    return {}


def save_jobs(jobs: list, path: str = "linkedin_jobs.json") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)


ALL_ROLES_FILE = "processed_jobs.json"


def merge_into_all_roles(linkedin_jobs: list, all_roles_path: str = ALL_ROLES_FILE) -> int:
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
    for job in linkedin_jobs:
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
