import hashlib
import json
import logging
import os
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
    RATE_LIMIT_NAUKRI, MAX_RETRIES_SCRAPER, REQUEST_TIMEOUT,
    JOBS_JSON, DUPLICATE_STOP_THRESHOLD
)

log = logging.getLogger("agent")

NAUKRI_API = "https://www.naukri.com/jobapi/v3/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "appid": "109",
    "systemid": "109",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.naukri.com/",
}

ALL_ROLES_FILE = JOBS_JSON
NAUKRI_OUTPUT = "naukri_jobs.json"

_search_cache = {}
_cache_lock = threading.Lock()

_last_stats = {
    "queries": 0, "pages": 0, "jobs_found": 0,
    "duplicates": 0, "new_jobs": 0, "failed_requests": 0,
    "total_duration": 0.0,
    "durations": [],
    "early_stopped": 0,
}

_rate_limiter = threading.Lock()
_last_request_time = 0.0

PROGRESS_BAR_STYLE = {
    "ascii": True,
    "ncols": 80,
    "bar_format": "{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
}


def _rate_limit():
    global _last_request_time
    with _rate_limiter:
        elapsed = time.time() - _last_request_time
        if elapsed < RATE_LIMIT_NAUKRI:
            time.sleep(RATE_LIMIT_NAUKRI - elapsed)
        _last_request_time = time.time()


def _cache_key(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _cached_fetch(url: str) -> tuple:
    ck = _cache_key(url)
    with _cache_lock:
        if ck in _search_cache:
            log.debug("  Naukri cache HIT: %s", url[:80])
            return _search_cache[ck], 0.0
    _rate_limit()
    start_ts = time.time()
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        data = json.loads(resp.read().decode())
        duration = time.time() - start_ts
        with _cache_lock:
            _search_cache[ck] = data
        return data, duration
    except urllib.error.HTTPError as e:
        raise
    except Exception as e:
        raise


def _extract_location(placeholders: list) -> str:
    if not placeholders:
        return "Hyderabad, India"
    for p in placeholders:
        label = (p.get("label") or "").strip()
        if label and "experience" not in label.lower():
            return label
    return placeholders[0].get("label", "Hyderabad, India")


def search_naukri(keyword: str, location: str = "Hyderabad", pages: int = 2, experience: str = None, job_age: int = 7) -> list:
    all_jobs = []
    seen_in_search = set()
    stop_early = False

    for page in range(1, pages + 1):
        if stop_early:
            _last_stats["early_stopped"] += 1
            log.debug("  Naukri early stop: %s / %s / %s page %s (duplicate threshold)", keyword, location, experience or "all", page)
            break

        params = {
            "searchType": "adv",
            "keyword": keyword,
            "location": location,
            "pageNo": page,
            "experienceType": EXPERIENCE_PARAMS.get("naukri", {}).get(experience, "all") if experience else "all",
            "jobAge": str(job_age),
        }
        url = f"{NAUKRI_API}?{urllib.parse.urlencode(params)}"

        log.debug("  Naukri: city=%s role=%s exp=%s page=%s age=%sd", location, keyword, experience or "all", page, job_age)
        start_ts = time.time()
        try:
            data, duration = _cached_fetch(url)
        except urllib.error.HTTPError as e:
            _last_stats["failed_requests"] += 1
            log.warning("  Naukri HTTP %s for %s / %s page %s: %s", e.code, keyword, location, page, e)
            break
        except Exception as e:
            _last_stats["failed_requests"] += 1
            log.warning("  Naukri error for %s / %s page %s: %s", keyword, location, page, e)
            break

        jobs = data.get("jobDetails", [])
        if not jobs:
            debug_info = data.get("noOfJobs", 0)
            log.debug("  Page %s: 0 jobs (totalJobs=%s)", page, debug_info)
            break

        _last_stats["pages"] += 1
        _last_stats["durations"].append(duration)

        dup_count = 0
        for job in jobs:
            jd = job.get("jdid") or job.get("jobId", "")
            if jd in seen_in_search:
                dup_count += 1
                continue
            seen_in_search.add(jd)
            all_jobs.append(job)

        if page > 1 and dup_count > 0:
            dup_ratio = dup_count / len(jobs)
            log.debug("  Page %s: %s jobs, %s dups (%.0f%%), total unique: %s", page, len(jobs), dup_count, dup_ratio * 100, len(all_jobs))
            if dup_ratio >= DUPLICATE_STOP_THRESHOLD:
                log.debug("  Stopping early at page %s (%.0f%% duplicates)", page, dup_ratio * 100)
                stop_early = True
        else:
            log.debug("  Page %s: %s jobs, total unique: %s (%.1fs)", page, len(jobs), len(all_jobs), duration)

    return all_jobs


def transform_naukri_job(raw: dict, category: str = "data_analyst", keyword: str = "") -> dict:
    title = (raw.get("title") or "").strip()
    company = (raw.get("companyName") or "").strip()
    location = _extract_location(raw.get("placeholders") or [])
    job_id = raw.get("jdid") or raw.get("jobId", "")
    description = (raw.get("jobDescription") or raw.get("description", "")).strip()
    date_str = datetime.date.today().isoformat()

    jd = raw.get("jdid") or ""
    url = f"https://www.naukri.com/job-details/{jd}" if jd else ""

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
    }


def _search_combo(keyword: str, category: str, city: str, experience: str, pages_per_search: int, job_age: int) -> list:
    _last_stats["queries"] += 1
    start_ts = time.time()
    raw_jobs = search_naukri(keyword, city, pages=pages_per_search, experience=experience, job_age=job_age)
    duration = time.time() - start_ts

    _last_stats["jobs_found"] += len(raw_jobs)

    seen_in_batch = set()
    transformed = []
    for raw in raw_jobs:
        jd = raw.get("jdid") or raw.get("jobId", "")
        if jd in seen_in_batch:
            continue
        seen_in_batch.add(jd)
        transformed.append(transform_naukri_job(raw, category=category, keyword=keyword))

    log.info("  Naukri: city=%s role=%s exp=%s \u2192 %s jobs (%.1fs)", city, keyword, experience, len(transformed), duration)
    return transformed


def fetch_all(location=None, pages_per_search=None, experience=None, job_age=7):
    global _last_stats, _search_cache
    _last_stats = {
        "queries": 0, "pages": 0, "jobs_found": 0,
        "duplicates": 0, "new_jobs": 0, "failed_requests": 0,
        "total_duration": 0.0, "durations": [],
        "early_stopped": 0,
    }

    if pages_per_search is None:
        pages_per_search = MAX_PAGES

    _search_cache = {}

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
    log.info("  Naukri: %s combos x %s pages (age=%sd), %s workers", len(combos), pages_per_search, job_age, CONCURRENT_WORKERS)

    try:
        from tqdm import tqdm
        pbar = tqdm(total=len(combos), desc="  Naukri", **PROGRESS_BAR_STYLE)
    except ImportError:
        pbar = None

    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = {}
        for keyword, category, city, exp in combos:
            future = executor.submit(_search_combo, keyword, category, city, exp, pages_per_search, job_age)
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
                log.warning("  Naukri combo failed: %s / %s / %s \u2014 %s", kw, city, exp, e)
            if pbar:
                pbar.update(1)

    if pbar:
        pbar.close()

    _last_stats["total_duration"] = time.time() - start_all
    _last_stats["jobs_found"] = len(all_jobs)

    log.info("Naukri fetch_all: %s queries, %s pages, %s jobs found, %s duplicates, %s failed, %.1fs total",
             _last_stats["queries"], _last_stats["pages"],
             _last_stats["jobs_found"], _last_stats["duplicates"],
             _last_stats["failed_requests"], _last_stats["total_duration"])

    return all_jobs


def get_last_stats():
    return dict(_last_stats)


def save_jobs(jobs: list, path: str = NAUKRI_OUTPUT):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    log.info("Saved %s Naukri jobs to %s", len(jobs), path)


def merge_into_all_roles(naukri_jobs: list, all_roles_path: str = ALL_ROLES_FILE):
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

    for job in naukri_jobs:
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

        existing.append(job)
        if url:
            existing_by_link[url] = job
        if jid:
            existing_by_id[jid] = job
        existing_by_key[key] = job
        new_count += 1

    _last_stats["new_jobs"] = new_count

    with open(all_roles_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    log.info("Merged %s new + %s updated Naukri jobs into %s", new_count, updated_count, all_roles_path)
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

    log.info("Fetching jobs from Naukri.com for location: %s", location or "ALL CITIES")
    jobs = fetch_all(location=location)
    save_jobs(jobs)

    if jobs:
        added = merge_into_all_roles(jobs)
        log.info("Done. %s new jobs added to %s", added, ALL_ROLES_FILE)
    else:
        log.warning("No jobs fetched from Naukri.")
