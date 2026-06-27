import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import (
    get_expanded_searches, CITIES, EXPERIENCE_LEVELS,
    EXPERIENCE_PARAMS, MAX_PAGES, CONCURRENT_WORKERS,
    RATE_LIMIT_LINKEDIN, MAX_RETRIES_SCRAPER, REQUEST_TIMEOUT,
    JOBS_JSON
)

log = logging.getLogger("agent")

LINKEDIN_BASE = "https://www.linkedin.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.linkedin.com/jobs/",
    "DNT": "1",
}

ALL_ROLES_FILE = JOBS_JSON
LINKEDIN_OUTPUT = "linkedin_jobs.json"

_last_stats = {
    "queries": 0, "pages": 0, "jobs_found": 0,
    "duplicates": 0, "new_jobs": 0, "failed_requests": 0,
    "total_duration": 0.0, "durations": [],
}

_rate_limiter = threading.Lock()
_last_request_time = 0.0


def _rate_limit():
    global _last_request_time
    with _rate_limiter:
        elapsed = time.time() - _last_request_time
        if elapsed < RATE_LIMIT_LINKEDIN:
            time.sleep(RATE_LIMIT_LINKEDIN - elapsed)
        _last_request_time = time.time()


def _fetch_url(url: str, headers: dict = None, max_retries: int = 3) -> str:
    h = {**HEADERS, **(headers or {})}
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            _rate_limit()
            req = urllib.request.Request(url, headers=h)
            resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
            html = resp.read()
            try:
                return html.decode("utf-8")
            except UnicodeDecodeError:
                return html.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code in (403, 429):
                log.debug("  LinkedIn HTTP %s, retrying (%s/%s)...", e.code, attempt, max_retries)
                time.sleep(3 * attempt)
                continue
            break
        except Exception as e:
            last_err = str(e)
            log.debug("  LinkedIn fetch error (%s/%s): %s", attempt, max_retries, e)
            time.sleep(2 * attempt)
            continue
    log.warning("  Failed to fetch %s: %s", url, last_err)
    return ""


def _clean_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def search_linkedin_api(keyword: str, location: str, start: int = 0, experience: str = None) -> list:
    params = {
        "keywords": keyword,
        "location": location,
        "start": str(start),
    }
    exp_val = EXPERIENCE_PARAMS.get("linkedin", {}).get(experience, "") if experience else ""
    if exp_val:
        params["f_E"] = exp_val

    url = f"{LINKEDIN_BASE}/jobs-guest/jobs/api/seeMoreJobPostings/search?{urllib.parse.urlencode(params)}"

    log.debug("  LinkedIn: city=%s role=%s exp=%s start=%s", location, keyword, experience or "all", start)
    log.debug("  URL: %s", url)

    html = _fetch_url(url)
    if not html:
        return []

    jobs = []
    li_pattern = re.compile(r'<li[^>]*class="[^"]*result-card[^"]*"[^>]*>(.*?)</li>', re.DOTALL)
    for match in li_pattern.finditer(html):
        card = match.group(1)
        try:
            job = _parse_job_card(card, keyword, location)
            if job:
                jobs.append(job)
        except Exception:
            continue

    return jobs


def _parse_job_card(card_html: str, keyword: str, location: str) -> dict:
    job_id = ""
    m = re.search(r'/jobs/view/(\d+)', card_html)
    if m:
        job_id = m.group(1)
    if not job_id:
        m = re.search(r'data-job-id="(\d+)"', card_html)
        if m:
            job_id = m.group(1)

    title = ""
    m = re.search(r'<h3[^>]*class="[^"]*result-card__title[^"]*"[^>]*>\s*(.*?)\s*</h3>', card_html, re.DOTALL)
    if m:
        title = _clean_html(m.group(1))
    if not title:
        m = re.search(r'<a[^>]*class="[^"]*result-card__full-card[^"]*"[^>]*title="([^"]*)"', card_html)
        if m:
            title = m.group(1)

    company = ""
    m = re.search(r'<h4[^>]*class="[^"]*result-card__subtitle[^"]*"[^>]*>\s*(.*?)\s*</h4>', card_html, re.DOTALL)
    if m:
        company = _clean_html(m.group(1))
    if not company:
        m = re.search(r'<a[^>]*class="[^"]*result-card__subtitle-link[^"]*"[^>]*>\s*(.*?)\s*</a>', card_html, re.DOTALL)
        if m:
            company = _clean_html(m.group(1))

    loc = location
    m = re.search(r'<span[^>]*class="[^"]*job-result-card__location[^"]*"[^>]*>\s*(.*?)\s*</span>', card_html, re.DOTALL)
    if m:
        loc = _clean_html(m.group(1))

    if not title and not job_id:
        return {}

    return {
        "title": title or "Unknown Position",
        "company": company or "Unknown Company",
        "location": loc,
        "job_id": f"linkedin_{job_id}" if job_id else f"linkedin_{keyword}_{company}".replace(" ", "_"),
        "description": "",
        "keyword": keyword,
        "url": f"{LINKEDIN_BASE}/jobs/view/{job_id}" if job_id else "",
    }


def fetch_job_description(job_id: str) -> str:
    if not job_id or job_id.startswith("linkedin_"):
        clean_id = job_id.replace("linkedin_", "") if job_id else ""
        if not clean_id or not clean_id.isdigit():
            return ""
    else:
        clean_id = job_id

    url = f"{LINKEDIN_BASE}/jobs-guest/jobs/api/jobPosting/{clean_id}"
    html = _fetch_url(url)
    if not html:
        return ""

    desc_patterns = [
        r'<section[^>]*class="[^"]*description[^"]*"[^>]*>(.*?)</section>',
        r'<div[^>]*class="[^"]*show-more-less-html[^"]*"[^>]*>(.*?)</div>',
    ]
    for pat in desc_patterns:
        m = re.search(pat, html, re.DOTALL)
        if m:
            desc = _clean_html(m.group(1))
            if len(desc) > 50:
                return desc

    return ""


def transform_linkedin_job(raw: dict, category: str = "data_analyst", keyword: str = "") -> dict:
    title = raw.get("title", "Unknown Position")
    company = raw.get("company", "Unknown Company")
    location = raw.get("location", "India")
    job_id = raw.get("job_id", "")
    description = raw.get("description", "")
    url = raw.get("url", "")

    clean_id = job_id.replace("linkedin_", "") if job_id else ""
    if clean_id and clean_id.isdigit() and not description:
        log.info("    Fetching description for %s @ %s...", title, company)
        description = fetch_job_description(clean_id)
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
    }


def _search_combo(keyword: str, category: str, city: str, experience: str, pages_per_search: int) -> list:
    log.info("  LinkedIn: city=%s role=%s exp=%s", city, keyword, experience)
    start_ts = time.time()
    seen_ids = set()
    all_jobs = []

    for page in range(pages_per_search):
        start = page * 10
        raw_jobs = search_linkedin_api(keyword, city, start=start, experience=experience)
        if not raw_jobs:
            if page == 0:
                log.debug("  No results for '%s' at %s exp=%s", keyword, city, experience)
            break

        for raw in raw_jobs:
            jid = raw.get("job_id", "")
            if jid in seen_ids:
                continue
            seen_ids.add(jid)
            transformed = transform_linkedin_job(raw, category=category, keyword=keyword)
            all_jobs.append(transformed)

        _last_stats["pages"] += 1
        log.debug("  Page %s: %s jobs (total unique: %s)", page + 1, len(raw_jobs), len(all_jobs))

    duration = time.time() - start_ts
    log.info("  LinkedIn: city=%s role=%s exp=%s → %s jobs (%.1fs)", city, keyword, experience, len(all_jobs), duration)
    _last_stats["queries"] += 1
    _last_stats["jobs_found"] += len(all_jobs)

    return all_jobs


def fetch_all(location=None, pages_per_search=None, experience=None):
    global _last_stats
    _last_stats = {
        "queries": 0, "pages": 0, "jobs_found": 0,
        "duplicates": 0, "new_jobs": 0, "failed_requests": 0,
        "total_duration": 0.0, "durations": [],
    }

    if pages_per_search is None:
        pages_per_search = MAX_PAGES

    searches = get_expanded_searches()
    cities = [location] if location else CITIES
    experiences = [experience] if experience else EXPERIENCE_LEVELS

    all_jobs = []
    seen_ids = set()

    combos = [(s["keyword"], s["category"], c, e)
              for s in searches
              for c in cities
              for e in experiences]

    start_all = time.time()

    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = {}
        for keyword, category, city, exp in combos:
            future = executor.submit(_search_combo, keyword, category, city, exp, pages_per_search)
            futures[future] = (keyword, city, exp)

        for future in as_completed(futures):
            try:
                jobs = future.result()
                for job in jobs:
                    jid = job.get("job_id", "")
                    if jid in seen_ids:
                        _last_stats["duplicates"] += 1
                        continue
                    seen_ids.add(jid)
                    all_jobs.append(job)
            except Exception as e:
                _last_stats["failed_requests"] += 1
                kw, city, exp = futures[future]
                log.warning("  LinkedIn combo failed: %s / %s / %s — %s", kw, city, exp, e)

    _last_stats["total_duration"] = time.time() - start_all
    _last_stats["jobs_found"] = len(all_jobs)

    log.info("LinkedIn fetch_all: %s queries, %s pages, %s jobs found, %s duplicates, %s failed, %.1fs total",
             _last_stats["queries"], _last_stats["pages"],
             _last_stats["jobs_found"], _last_stats["duplicates"],
             _last_stats["failed_requests"], _last_stats["total_duration"])

    return all_jobs


def get_last_stats():
    return dict(_last_stats)


def save_jobs(jobs: list, path: str = LINKEDIN_OUTPUT):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    log.info("Saved %s LinkedIn jobs to %s", len(jobs), path)


def merge_into_all_roles(linkedin_jobs: list, all_roles_path: str = ALL_ROLES_FILE):
    if os.path.exists(all_roles_path):
        with open(all_roles_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = []

    existing_by_link = {}
    existing_by_id = {}
    existing_by_key = {}
    for job in existing:
        url = job.get("url", "") or ""
        if url:
            existing_by_link[url] = job
        jid = job.get("job_id", "")
        if jid:
            existing_by_id[jid] = job
        key = (job.get("title", ""), job.get("company", ""), job.get("location", ""))
        existing_by_key[key] = job

    new_count = 0
    updated_count = 0

    for job in linkedin_jobs:
        url = job.get("url", "") or ""
        jid = job.get("job_id", "")
        key = (job.get("title", ""), job.get("company", ""), job.get("location", ""))

        if url and url in existing_by_link:
            existing_job = existing_by_link[url]
            if (existing_job.get("description") != job.get("description") or
                    existing_job.get("title") != job.get("title")):
                idx = existing.index(existing_job)
                existing[idx] = job
                existing_by_link[url] = job
                updated_count += 1
            continue

        if jid and jid in existing_by_id:
            existing_job = existing_by_id[jid]
            if (existing_job.get("description") != job.get("description") or
                    existing_job.get("title") != job.get("title")):
                idx = existing.index(existing_job)
                existing[idx] = job
                existing_by_id[jid] = job
                updated_count += 1
            continue

        if key in existing_by_key:
            continue

        out = {k: v for k, v in job.items() if not k.startswith("_")}
        out.pop("keyword", None)
        existing.append(out)
        if url:
            existing_by_link[url] = out
        if jid:
            existing_by_id[jid] = out
        existing_by_key[key] = out
        new_count += 1

    _last_stats["new_jobs"] = new_count

    with open(all_roles_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    log.info("Merged %s new + %s updated LinkedIn jobs into %s", new_count, updated_count, all_roles_path)
    return new_count


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("agent")

    import sys
    location = sys.argv[1] if len(sys.argv) > 1 else None

    log.info("Fetching jobs from LinkedIn for location: %s", location or "ALL CITIES")
    jobs = fetch_all(location=location)
    save_jobs(jobs)

    if jobs:
        added = merge_into_all_roles(jobs)
        log.info("Done. %s new jobs added to %s", added, ALL_ROLES_FILE)
    else:
        log.warning("No jobs fetched from LinkedIn.")
