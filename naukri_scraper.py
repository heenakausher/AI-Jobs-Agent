"""Naukri.com scraper — Playwright-only HTML scraping."""

import datetime
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from utils.base_scraper import BaseScraper
from utils.playwright_helpers import fetch_page_html

log = logging.getLogger("agent")


class NaukriScraper(BaseScraper):
    """Naukri.com job scraper."""

    def __init__(self, stop_event: Any = None) -> None:
        super().__init__("Naukri", stop_event=stop_event)

    def search_keyword(
        self,
        keyword: str,
        category: str,
        location: str,
        page: int,
        job_age_hours: int,
    ) -> List[Dict[str, Any]]:
        self.rate_limiter.wait()

        import urllib.parse
        form_keyword = keyword.lower().strip()
        form_location = location.lower().strip()

        search_url = (
            f"https://www.naukri.com/"
            f"{urllib.parse.quote(form_keyword)}-jobs-in-{urllib.parse.quote(form_location)}"
        )

        if page > 0:
            search_url += f"?pageNo={page + 1}"

        html = fetch_page_html(search_url, wait_selector=".jobTuple,.title,.job-card")
        if not html:
            return []

        return self._parse_html_jobs(html, keyword, location)

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

    def _parse_html_jobs(self, html: str, keyword: str, location: str) -> list:
        """Parse job listings from Naukri HTML page."""
        jobs = []
        seen_ids = set()

        # Try extracting from embedded JSON data in script tags
        for m in re.finditer(
            r'<script[^>]*type="application/json"[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        ):
            try:
                data = json.loads(m.group(1))
                job_list = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("searchResults", {})
                    .get("jobDetails", [])
                    or data.get("props", {})
                    .get("pageProps", {})
                    .get("jobList", [])
                )
                for j in job_list:
                    jid = j.get("jobId") or j.get("id", "")
                    if jid and jid in seen_ids:
                        continue
                    if jid:
                        seen_ids.add(jid)
                    jobs.append({
                        "title": (j.get("title") or j.get("jobTitle", "")).strip(),
                        "company": (j.get("companyName") or j.get("company", "")).strip(),
                        "location": (j.get("location") or j.get("placeholders", [{}])[0].get("label", location)).strip(),
                        "job_id": jid,
                        "description": (j.get("jobDescription") or j.get("description", "")).strip(),
                        "keyword": keyword,
                        "url": f"https://www.naukri.com/job-details/{jid}" if jid else "",
                    })
                if jobs:
                    return jobs
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        # Fallback: parse from HTML structure
        for m in re.finditer(
            r'<article[^>]*class="[^"]*jobTuple[^"]*"[^>]*>(.*?)</article>',
            html, re.DOTALL,
        ):
            card = m.group(1)
            title = ""
            m2 = re.search(r'<a[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</a>', card, re.DOTALL)
            if m2:
                title = re.sub(r'<[^>]+>', ' ', m2.group(1)).strip()
            company = ""
            m2 = re.search(r'<a[^>]*class="[^"]*subTitle[^"]*"[^>]*>(.*?)</a>', card, re.DOTALL)
            if m2:
                company = re.sub(r'<[^>]+>', ' ', m2.group(1)).strip()
            loc = location
            m2 = re.search(r'<span[^>]*class="[^"]*loc[^"]*"[^>]*>(.*?)</span>', card, re.DOTALL)
            if m2:
                loc = re.sub(r'<[^>]+>', ' ', m2.group(1)).strip()
            if not title:
                continue
            jobs.append({
                "title": title,
                "company": company or "Unknown Company",
                "location": loc,
                "job_id": f"naukri_{keyword}_{company}".replace(" ", "_"),
                "description": "",
                "keyword": keyword,
                "url": "",
            })
        return jobs


def fetch_all(job_age_hours: int = 24, stop_event: Any = None) -> List[Dict[str, Any]]:
    scraper = NaukriScraper(stop_event=stop_event)
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
