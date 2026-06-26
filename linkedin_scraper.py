import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import datetime
import subprocess
import sys

log = logging.getLogger("agent")

LINKEDIN_BASE = "https://www.linkedin.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.linkedin.com/jobs/",
    "DNT": "1",
}

LINKEDIN_SEARCHES = [
    {"keyword": "Data Analyst", "category": "data_analyst"},
    {"keyword": "Business Analyst", "category": "data_analyst"},
    {"keyword": "Business Intelligence", "category": "data_analyst"},
    {"keyword": "Data Analytics", "category": "data_analyst"},
    {"keyword": "Power BI", "category": "data_analyst"},
    {"keyword": "Financial Analyst", "category": "finance_roles"},
    {"keyword": "Finance", "category": "finance_roles"},
    {"keyword": "SAP FICO", "category": "finance_roles"},
    {"keyword": "Agentic AI", "category": "agentic_ai"},
    {"keyword": "AI Engineer", "category": "agentic_ai"},
    {"keyword": "Machine Learning", "category": "agentic_ai"},
    {"keyword": "GenAI", "category": "agentic_ai"},
    {"keyword": "LLM", "category": "agentic_ai"},
    {"keyword": "RAG", "category": "agentic_ai"},
    {"keyword": "AI Intern", "category": "fresher_ai_ml"},
    {"keyword": "Finance Intern", "category": "fresher_ai_ml"},
]

ALL_ROLES_FILE = "processed_jobs.json"
LINKEDIN_OUTPUT = "linkedin_jobs.json"


def _fetch_url(url: str, headers: dict = None, max_retries: int = 3) -> str:
    h = {**HEADERS, **(headers or {})}
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=h)
            resp = urllib.request.urlopen(req, timeout=30)
            html = resp.read()
            try:
                return html.decode("utf-8")
            except UnicodeDecodeError:
                return html.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code in (403, 429):
                time.sleep(3 * attempt)
                continue
            break
        except Exception as e:
            last_err = str(e)
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


def _extract_json_from_script(html: str, pattern: str) -> dict:
    m = re.search(pattern, html, re.DOTALL)
    if m:
        raw = m.group(1)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {}


def search_linkedin_api(keyword: str, location: str, start: int = 0) -> list:
    url = f"{LINKEDIN_BASE}/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={urllib.parse.quote(keyword)}&location={urllib.parse.quote(location)}&start={start}"
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


def transform_linkedin_job(raw: dict, category: str = "data_analyst") -> dict:
    title = raw.get("title", "Unknown Position")
    company = raw.get("company", "Unknown Company")
    location = raw.get("location", "India")
    job_id = raw.get("job_id", "")
    description = raw.get("description", "")

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
        "_source": "LinkedIn",
    }


def fetch_all(location: str = "Hyderabad", pages_per_search: int = 2) -> list:
    seen_ids = set()
    all_transformed = []

    for search in LINKEDIN_SEARCHES:
        kw = search["keyword"]
        cat = search["category"]
        log.info("Searching LinkedIn for '%s' (%s)...", kw, cat)

        for page in range(pages_per_search):
            start = page * 10
            raw_jobs = search_linkedin_api(kw, location, start=start)
            if not raw_jobs:
                if page == 0:
                    log.warning("  No results for '%s' at %s", kw, location)
                break

            for raw in raw_jobs:
                jid = raw.get("job_id", "")
                if jid in seen_ids:
                    continue
                seen_ids.add(jid)
                transformed = transform_linkedin_job(raw, category=cat)
                all_transformed.append(transformed)

            log.info("  Page %s: %s jobs (total unique: %s)", page + 1, len(raw_jobs), len(all_transformed))
            time.sleep(2)

    return all_transformed


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

    existing_ids = {}
    for job in existing:
        jid = job.get("job_id", "")
        if jid:
            existing_ids[jid] = True
        key = (job.get("title", ""), job.get("company", ""))
        existing_ids[key] = True

    new_count = 0
    for job in linkedin_jobs:
        jid = job.get("job_id", "")
        if jid and jid in existing_ids:
            continue
        key = (job.get("title", ""), job.get("company", ""))
        if key in existing_ids:
            continue
        out = {k: v for k, v in job.items() if not k.startswith("_")}
        out.pop("keyword", None)
        existing.append(out)
        existing_ids[jid] = True
        existing_ids[key] = True
        new_count += 1

    with open(all_roles_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    log.info("Merged %s new LinkedIn jobs into %s", new_count, all_roles_path)
    return new_count


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("agent")

    location = sys.argv[1] if len(sys.argv) > 1 else "Hyderabad"
    log.info("Fetching jobs from LinkedIn for location: %s", location)
    jobs = fetch_all(location=location, pages_per_search=2)
    save_jobs(jobs)
    if jobs:
        added = merge_into_all_roles(jobs)
        log.info("Done. %s new jobs added to %s", added, ALL_ROLES_FILE)
    else:
        log.warning("No jobs fetched from LinkedIn.")
