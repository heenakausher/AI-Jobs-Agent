"""Indeed.com scraper — Playwright-only HTML scraping."""

import datetime
import json
import logging
import os
import re
import time
from typing import Any, Dict, List

from utils.base_scraper import BaseScraper
from utils.playwright_helpers import fetch_page_html

log = logging.getLogger("agent")

INDEED_BASE = "https://www.indeed.com"


class IndeedScraper(BaseScraper):
    """Indeed.com job scraper."""

    def __init__(self) -> None:
        super().__init__("Indeed")

    def search_keyword(
        self,
        keyword: str,
        category: str,
        location: str,
        page: int,
        job_age_hours: int,
    ) -> List[Dict[str, Any]]:
        self.rate_limiter.wait()

        fromage = max(1, job_age_hours // 24)
        start = page * 10
        params = f"q={keyword.replace(' ', '+')}&l={location.replace(' ', '+')}&start={start}&sort=date&fromage={fromage}"
        url = f"{INDEED_BASE}/jobs?{params}"

        html = fetch_page_html(url, wait_selector="[class*=job_seen_beacon],[class*=tapItem]")
        if not html:
            return []

        jobs = self._parse_mosaic(html, keyword, location)
        if jobs:
            return jobs
        return self._parse_html_cards(html, keyword, location)

    def transform_job(self, raw: Dict[str, Any], keyword: str, category: str) -> Dict[str, Any]:
        title = raw.get("title", "Unknown Position")
        company = raw.get("company", "Unknown Company")
        location = raw.get("location", "India")
        job_id = raw.get("job_id", "")
        description = raw.get("description", "")
        job_key = raw.get("job_key", "")
        url = raw.get("url", "")

        if job_key and not description:
            description = self._fetch_description(job_key)
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
            "source": "Indeed",
            "keyword": keyword,
        }

    def _extract_json_balanced(self, text: str, start_marker: str) -> Optional[str]:
        """Extract a JSON object from text starting after start_marker by balancing braces."""
        idx = text.find(start_marker)
        if idx == -1:
            return None
        start = idx + len(start_marker)
        brace_depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if ch == '\\' and not escape:
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
            if not in_string:
                if ch == '{':
                    if brace_depth == 0:
                        start = i
                    brace_depth += 1
                elif ch == '}':
                    brace_depth -= 1
                    if brace_depth == 0:
                        raw = text[start:i + 1]
                        try:
                            return json.loads(raw)
                        except json.JSONDecodeError:
                            return None
            escape = False
        return None

    def _parse_mosaic(self, html: str, keyword: str, location: str) -> list:
        markers = ['window._initialData=', 'window.mosaic.providerData=']
        for marker in markers:
            data = self._extract_json_balanced(html, marker)
            if not data:
                continue
            results = (
                data.get("results")
                or data.get("jobList")
                or data.get("jobs")
                or data.get("metaData", {}).get("results")
                or data.get("searchMeta", {}).get("results")
            )
            if not results:
                continue
            parsed = []
            for r in results:
                jk = r.get("jk") or r.get("jobkey", "")
                if not jk:
                    continue
                parsed.append({
                    "title": (r.get("title") or r.get("jobTitle", "")).strip(),
                    "company": (r.get("company") or r.get("companyName", "")).strip(),
                    "location": (r.get("location") or r.get("formattedLocation", location)).strip(),
                    "job_id": f"indeed_{jk}",
                    "job_key": jk,
                    "description": self._clean_html(r.get("snippet", "") or r.get("description", "")),
                    "keyword": keyword,
                    "url": f"{INDEED_BASE}/viewjob?jk={jk}",
                })
            return parsed
        return []

    def _parse_html_cards(self, html: str, keyword: str, location: str) -> list:
        parsed = []
        seen_jks = set()
        card_pattern = r'<div[^>]*class="[^"]*job_seen_beacon[^"]*"[^>]*>.*?</div>\s*</div>\s*</td>'
        for match in re.finditer(card_pattern, html, re.DOTALL):
            card = match.group(0)
            try:
                job = self._parse_single_card(card, keyword, location)
                if job and job["job_id"] not in seen_jks:
                    seen_jks.add(job["job_id"])
                    parsed.append(job)
            except Exception:
                continue
        return parsed

    def _parse_single_card(self, html: str, keyword: str, location: str) -> dict:
        title = ""
        m = re.search(r'<h2[^>]*class="[^"]*jobTitle[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>', html, re.DOTALL)
        if m:
            title = self._clean_html(m.group(1))
        if not title:
            m = re.search(r'<a[^>]*class="[^"]*jcs-JobTitle[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL)
            if m:
                title = self._clean_html(m.group(1))

        company = ""
        m = re.search(r'<span[^>]*class="[^"]*company[^"]*"[^>]*>\s*(.*?)\s*</span>', html, re.DOTALL)
        if m:
            company = self._clean_html(m.group(1))

        loc = location
        m = re.search(r'<div[^>]*class="[^"]*location[^"]*"[^>]*>\s*(.*?)\s*</div>', html, re.DOTALL)
        if m:
            loc = self._clean_html(m.group(1))

        jk = ""
        m = re.search(r'data-jk="([^"]+)"', html)
        if m:
            jk = m.group(1)
        if not jk:
            m = re.search(r'/viewjob\?jk=([^"&]+)', html)
            if m:
                jk = m.group(1)

        snippet = ""
        m = re.search(r'<div[^>]*class="[^"]*summary[^"]*"[^>]*>\s*(.*?)\s*</div>', html, re.DOTALL)
        if m:
            snippet = self._clean_html(m.group(1))

        if not title and not jk:
            return {}

        return {
            "title": title or "Unknown Position",
            "company": company or "Unknown Company",
            "location": loc,
            "job_id": f"indeed_{jk}" if jk else f"indeed_{keyword}_{company}".replace(" ", "_"),
            "job_key": jk,
            "description": snippet or "",
            "keyword": keyword,
            "url": f"{INDEED_BASE}/viewjob?jk={jk}" if jk else "",
        }

    def _fetch_description(self, job_key: str) -> str:
        if not job_key:
            return ""
        url = f"{INDEED_BASE}/viewjob?jk={job_key}"
        html = fetch_page_html(url, wait_selector="#jobDescriptionText")
        if not html:
            return ""

        m = re.search(r'<div[^>]*id="[^"]*jobDescriptionText[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
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
    scraper = IndeedScraper()
    return scraper.search_all_variants(job_age_hours=job_age_hours)


def get_last_stats() -> dict:
    return {}


def save_jobs(jobs: list, path: str = "indeed_jobs.json") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)


ALL_ROLES_FILE = "processed_jobs.json"


def merge_into_all_roles(indeed_jobs: list, all_roles_path: str = ALL_ROLES_FILE) -> int:
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
    for job in indeed_jobs:
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
