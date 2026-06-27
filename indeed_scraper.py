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
    MAX_PAGES, CONCURRENT_WORKERS,
    RATE_LIMIT_INDEED, MAX_RETRIES_SCRAPER, REQUEST_TIMEOUT,
    JOBS_JSON
)

log = logging.getLogger("agent")

INDEED_BASE = "https://www.indeed.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.indeed.com/",
    "DNT": "1",
}

ALL_ROLES_FILE = JOBS_JSON
INDEED_OUTPUT = "indeed_jobs.json"

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
        if elapsed < RATE_LIMIT_INDEED:
            time.sleep(RATE_LIMIT_INDEED - elapsed)
        _last_request_time = time.time()


def _fetch_url(url: str, headers: dict = None, max_retries: int = 2) -> str:
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
                log.warning("  Indeed HTTP %s, retrying (%s/%s)...", e.code, attempt, max_retries)
                time.sleep(3)
                continue
            break
        except Exception as e:
            last_err = str(e)
            log.warning("  Indeed fetch error (%s/%s): %s", attempt, max_retries, e)
            time.sleep(2)
            continue
    log.warning("  Failed to fetch %s: %s", url, last_err)
    return ""


def _extract_json_from_script(html: str, pattern: str) -> dict:
    m = re.search(pattern, html)
    if m:
        raw = m.group(1)
        raw = raw.replace("&q;", '"').replace("&l;", "<").replace("&g;", ">")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {}


def _clean_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def search_indeed(keyword: str, location: str = "Hyderabad", start: int = 0) -> list:
    params = {
        "q": keyword,
        "l": location,
        "start": str(start),
        "sort": "date",
    }
    url = f"{INDEED_BASE}/jobs?{urllib.parse.urlencode(params)}"

    log.debug("  Indeed: city=%s role=%s start=%s", location, keyword, start)
    log.debug("  URL: %s", url)

    html = _fetch_url(url)
    if not html:
        return []

    jobs = []
    jobs.extend(_parse_from_mosaic_data(html, keyword, location))
    if jobs:
        return jobs
    jobs.extend(_parse_from_html_cards(html, keyword, location))
    return jobs


def _parse_from_mosaic_data(html: str, keyword: str, location: str) -> list:
    patterns = [
        r'window\._initialData\s*=\s*(\{.+?\});',
        r'window\.mosaic\.providerData\s*=\s*(\{.+?\});',
        r'var\s+mosaic\s*=\s*(\{.+?\});',
    ]
    for pat in patterns:
        data = _extract_json_from_script(html, pat)
        if not data:
            continue
        try:
            results = data.get("results", []) or data.get("jobList", []) or data.get("jobs", [])
            if not results:
                meta = data.get("metaData", {}) or data.get("searchMeta", {})
                results = meta.get("results", []) if meta else []
        except AttributeError:
            continue
        if not results:
            continue

        parsed = []
        for r in results:
            jk = r.get("jk") or r.get("jobkey", "")
            if not jk:
                continue
            title = (r.get("title") or r.get("jobTitle", "")).strip()
            company = (r.get("company") or r.get("companyName", "")).strip()
            loc = (r.get("location") or r.get("formattedLocation", location)).strip()
            snippet = (r.get("snippet") or r.get("description", "")).strip()
            desc = _clean_html(snippet)
            parsed.append({
                "title": title,
                "company": company,
                "location": loc,
                "job_id": f"indeed_{jk}",
                "job_key": jk,
                "description": desc,
                "keyword": keyword,
                "url": f"{INDEED_BASE}/viewjob?jk={jk}",
            })
        return parsed
    return []


def _parse_from_html_cards(html: str, keyword: str, location: str) -> list:
    parsed = []

    card_patterns = [
        r'<div[^>]*class="[^"]*job_seen_beacon[^"]*"[^>]*>.*?</div>\s*</div>\s*</td>',
        r'<div[^>]*class="[^"]*jobsearch-SerpJobCard[^"]*"[^>]*>.*?<div[^>]*class="[^"]*footer[^"]*"',
        r'<li[^>]*class="[^"]*job-search-results__list-item[^"]*"[^>]*>.*?</li>',
    ]

    seen_jks = set()
    for pat in card_patterns:
        card_matches = re.findall(pat, html, re.DOTALL)
        for card_html in card_matches:
            try:
                job = _parse_single_card(card_html, keyword, location)
                if job and job["job_id"] not in seen_jks:
                    seen_jks.add(job["job_id"])
                    parsed.append(job)
            except Exception:
                continue
        if parsed:
            break

    return parsed


def _parse_single_card(card_html: str, keyword: str, location: str) -> dict:
    title = ""
    m = re.search(r'<a[^>]*class="[^"]*jobtitle[^"]*"[^>]*>\s*(.*?)\s*</a>', card_html, re.DOTALL | re.IGNORECASE)
    if m:
        title = _clean_html(m.group(1))
    if not title:
        m = re.search(r'<h2[^>]*class="[^"]*jobTitle[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>', card_html, re.DOTALL)
        if m:
            title = _clean_html(m.group(1))
    if not title:
        m = re.search(r'<a[^>]*id="[^"]*job[^"]*"[^>]*>\s*(.*?)\s*</a>', card_html, re.DOTALL)
        if m:
            title = _clean_html(m.group(1))

    company = ""
    m = re.search(r'<span[^>]*class="[^"]*company[^"]*"[^>]*>\s*(.*?)\s*</span>', card_html, re.DOTALL | re.IGNORECASE)
    if m:
        company = _clean_html(m.group(1))

    loc = location
    m = re.search(r'<div[^>]*class="[^"]*location[^"]*"[^>]*>\s*(.*?)\s*</div>', card_html, re.DOTALL | re.IGNORECASE)
    if m:
        loc = _clean_html(m.group(1))

    jk = ""
    m = re.search(r'data-jk="([^"]+)"', card_html)
    if m:
        jk = m.group(1)
    if not jk:
        m = re.search(r'/viewjob\?jk=([^"&]+)', card_html)
        if m:
            jk = m.group(1)

    snippet = ""
    m = re.search(r'<div[^>]*class="[^"]*summary[^"]*"[^>]*>\s*(.*?)\s*</div>', card_html, re.DOTALL | re.IGNORECASE)
    if m:
        snippet = _clean_html(m.group(1))

    if not title and not jk:
        return {}

    return {
        "title": title or "Unknown Position",
        "company": company or "Unknown Company",
        "location": loc,
        "job_id": f"indeed_{jk}" if jk else f"indeed_{keyword}_{company}".replace(" ", "_"),
        "job_key": jk,
        "description": snippet or f"Position: {title} at {company}",
        "keyword": keyword,
        "url": f"{INDEED_BASE}/viewjob?jk={jk}" if jk else "",
    }


def fetch_job_description(job_key: str) -> str:
    if not job_key:
        return ""
    url = f"{INDEED_BASE}/viewjob?jk={job_key}"
    html = _fetch_url(url)
    if not html:
        return ""

    desc_patterns = [
        r'<div[^>]*id="[^"]*jobDescriptionText[^"]*"[^>]*>(.*?)</div>\s*<div[^>]*class="[^"]*jobsearch-JobComponent',
        r'<div[^>]*id="[^"]*jobDescriptionText[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        r'<div[^>]*class="[^"]*jobsearch-jobDescriptionText[^"]*"[^>]*>(.*?)</div>',
    ]
    for pat in desc_patterns:
        m = re.search(pat, html, re.DOTALL)
        if m:
            desc = _clean_html(m.group(1))
            if len(desc) > 50:
                return desc

    script_data = _extract_json_from_script(html, r'__NEXT_DATA__\s*=\s*(\{.+?\});')
    if script_data:
        try:
            desc = (script_data.get("props", {})
                    .get("pageProps", {})
                    .get("jobDetails", {})
                    .get("sanitizedJobDescription", ""))
            if desc:
                return _clean_html(desc)
        except AttributeError:
            pass

    return ""


def transform_indeed_job(raw: dict, category: str = "data_analyst", keyword: str = "") -> dict:
    title = raw.get("title", "Unknown Position")
    company = raw.get("company", "Unknown Company")
    location = raw.get("location", "Hyderabad, India")
    job_id = raw.get("job_id", "")
    description = raw.get("description", "")
    job_key = raw.get("job_key", "")
    url = raw.get("url", "")

    if job_key and not description:
        log.info("    Fetching description for %s @ %s...", title, company)
        description = fetch_job_description(job_key)
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
    }


def _search_combo(keyword: str, category: str, city: str, pages_per_search: int) -> list:
    log.info("  Indeed: city=%s role=%s", city, keyword)
    start_ts = time.time()
    seen_ids = set()
    all_jobs = []

    for page in range(pages_per_search):
        start = page * 10
        raw_jobs = search_indeed(keyword, city, start=start)
        if not raw_jobs:
            if page == 0:
                log.debug("  No results for '%s' at %s", keyword, city)
            break

        for raw in raw_jobs:
            jid = raw.get("job_id", "")
            if jid in seen_ids:
                continue
            seen_ids.add(jid)
            transformed = transform_indeed_job(raw, category=category, keyword=keyword)
            all_jobs.append(transformed)

        _last_stats["pages"] += 1
        log.debug("  Page %s: %s jobs (total unique: %s)", page + 1, len(raw_jobs), len(all_jobs))

    duration = time.time() - start_ts
    log.info("  Indeed: city=%s role=%s → %s jobs (%.1fs)", city, keyword, len(all_jobs), duration)
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

    all_jobs = []
    seen_ids = set()

    combos = [(s["keyword"], s["category"], c)
              for s in searches
              for c in cities]

    start_all = time.time()

    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
        futures = {}
        for keyword, category, city in combos:
            future = executor.submit(_search_combo, keyword, category, city, pages_per_search)
            futures[future] = (keyword, city)

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
                kw, city = futures[future]
                log.warning("  Indeed combo failed: %s / %s — %s", kw, city, e)

    _last_stats["total_duration"] = time.time() - start_all
    _last_stats["jobs_found"] = len(all_jobs)

    log.info("Indeed fetch_all: %s queries, %s pages, %s jobs found, %s duplicates, %s failed, %.1fs total",
             _last_stats["queries"], _last_stats["pages"],
             _last_stats["jobs_found"], _last_stats["duplicates"],
             _last_stats["failed_requests"], _last_stats["total_duration"])

    return all_jobs


def get_last_stats():
    return dict(_last_stats)


def save_jobs(jobs: list, path: str = INDEED_OUTPUT):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    log.info("Saved %s Indeed jobs to %s", len(jobs), path)


def merge_into_all_roles(indeed_jobs: list, all_roles_path: str = ALL_ROLES_FILE):
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

    for job in indeed_jobs:
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
        out.pop("job_key", None)
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

    log.info("Merged %s new + %s updated Indeed jobs into %s", new_count, updated_count, all_roles_path)
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

    log.info("Fetching jobs from Indeed.com for location: %s", location or "ALL CITIES")
    jobs = fetch_all(location=location)
    save_jobs(jobs)

    if jobs:
        added = merge_into_all_roles(jobs)
        log.info("Done. %s new jobs added to %s", added, ALL_ROLES_FILE)
    else:
        log.warning("No jobs fetched from Indeed.")
