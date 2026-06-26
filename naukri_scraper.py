import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import datetime

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

NAUKRI_SEARCHES = [
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
NAUKRI_OUTPUT = "naukri_jobs.json"


def _extract_location(placeholders: list) -> str:
    if not placeholders:
        return "Hyderabad, India"
    for p in placeholders:
        label = (p.get("label") or "").strip()
        if label and "experience" not in label.lower():
            return label
    return placeholders[0].get("label", "Hyderabad, India")


def search_naukri(keyword: str, location: str = "Hyderabad", pages: int = 2) -> list:
    all_jobs = []
    for page in range(1, pages + 1):
        params = {
            "searchType": "adv",
            "keyword": keyword,
            "location": location,
            "pageNo": page,
            "experienceType": "all",
            "jobAge": "30",
        }
        url = f"{NAUKRI_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read().decode())
            jobs = data.get("jobDetails", [])
            if not jobs:
                break
            all_jobs.extend(jobs)
            log.info("  Page %s: %s jobs", page, len(jobs))
            time.sleep(1)
        except Exception as e:
            log.warning("  API error on page %s: %s", page, e)
            break
    return all_jobs


def transform_naukri_job(raw: dict, category: str = "data_analyst") -> dict:
    title = (raw.get("title") or "").strip()
    company = (raw.get("companyName") or "").strip()
    location = _extract_location(raw.get("placeholders") or [])
    job_id = raw.get("jdid") or raw.get("jobId", "")
    description = (raw.get("jobDescription") or raw.get("description", "")).strip()
    date_str = datetime.date.today().isoformat()

    return {
        "category": category,
        "title": title,
        "company": company,
        "location": location,
        "date": date_str,
        "job_id": job_id,
        "description": description,
    }


def fetch_all(location: str = "Hyderabad", pages_per_search: int = 2) -> list:
    seen_ids = set()
    all_transformed = []

    for search in NAUKRI_SEARCHES:
        kw = search["keyword"]
        cat = search["category"]
        log.info("Searching Naukri for '%s' (%s)...", kw, cat)
        raw_jobs = search_naukri(kw, location, pages=pages_per_search)

        for raw in raw_jobs:
            jd = raw.get("jdid") or raw.get("jobId", "")
            if jd in seen_ids:
                continue
            seen_ids.add(jd)

            transformed = transform_naukri_job(raw, category=cat)
            all_transformed.append(transformed)

        log.info("  %s total unique so far: %s", kw, len(all_transformed))

    return all_transformed


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

    existing_ids = {}
    for job in existing:
        jid = job.get("job_id", "")
        if jid:
            existing_ids[jid] = True
        key = (job.get("title", ""), job.get("company", ""))
        existing_ids[key] = True

    new_count = 0
    for job in naukri_jobs:
        jid = job.get("job_id", "")
        if jid and jid in existing_ids:
            continue
        key = (job.get("title", ""), job.get("company", ""))
        if key in existing_ids:
            continue
        existing.append(job)
        existing_ids[jid] = True
        existing_ids[key] = True
        new_count += 1

    with open(all_roles_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    log.info("Merged %s new Naukri jobs into %s", new_count, all_roles_path)
    return new_count


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("agent")

    import sys

    location = sys.argv[1] if len(sys.argv) > 1 else "Hyderabad"

    log.info("Fetching jobs from Naukri.com for location: %s", location)
    jobs = fetch_all(location=location, pages_per_search=2)
    save_jobs(jobs)

    if jobs:
        added = merge_into_all_roles(jobs)
        log.info("Done. %s new jobs added to %s", added, ALL_ROLES_FILE)
    else:
        log.warning("No jobs fetched from Naukri.")
