"""AI Jobs Agent — main pipeline orchestrator.

Handles scraping, dedup, scoring, resume generation, reports, and dashboard.
"""

import json
import logging
import os
import re
import sys
import time
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from groq_api import query_groq
import naukri_scraper
import indeed_scraper
import linkedin_scraper
import auto_scorer
from prompts import (
    detect_profile, classify_job_profile, build_system_prompt,
    build_cover_letter_prompt, extract_delimited, extract_score,
    PROFILES,
)
from resume_reviewer import review_and_improve
from config import (
    CITIES, MIN_AI_SCORE, OUTPUT_DIR, JOBS_JSON, CV_FILE,
    SCORE_CACHE, PROGRESS_FILE, STATS_FILE, HEALTH_FILE,
    CLIENT_SECRET_FILE, TOKEN_FILE, SHEET_ID, SCOPES,
    GENERATION_MODEL, OUTPUT_DATE_DIR, MAX_WORKERS,
    HEALTH_CONSECUTIVE_ZERO_THRESHOLD, MAX_PAGES_PER_SEARCH,
    GITHUB_USERNAME, REUSE_THRESHOLD, MIN_ATS_SCORE,
    SEARCH_KEYWORDS, SEARCH_CITIES, SEARCH_MODES,
)
from utils.fingerprint import Deduplicator
from utils.reports import (
    write_jobs_scraped, write_jobs_filtered,
    write_recommended_jobs, write_applied_jobs,
)
from utils.dashboard import generate_dashboard
from utils.metrics import MetricsTracker
from utils.github_fetcher import get_github_projects_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("agent.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("agent")

metrics = MetricsTracker()

# ── Google Sheets helpers ────────────────────────────────────────

def get_sheets_token() -> str:
    if not os.path.exists(TOKEN_FILE):
        log.error("No token.json found. Run: python3 auth_sheets.py step1")
        sys.exit(1)
    with open(TOKEN_FILE) as f:
        tok = json.load(f)
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as AuthRequest
    creds = Credentials(
        token=tok.get("token"),
        refresh_token=tok.get("refresh_token"),
        token_uri=tok.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=tok.get("client_id"),
        client_secret=tok.get("client_secret"),
        scopes=tok.get("scopes", SCOPES),
    )
    if not creds.valid:
        creds.refresh(AuthRequest())
        tok["token"] = creds.token
        tok["expiry"] = creds.expiry.isoformat() if creds.expiry else tok.get("expiry")
        with open(TOKEN_FILE, "w") as f:
            json.dump(tok, f, indent=2)
    return creds.token


def _ensure_sheet_headers(token: str, max_retries: int = 3):
    import urllib.request, urllib.error
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/A1:G1"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        existing = json.loads(resp.read().decode())
        if existing.get("values"):
            return
    except urllib.error.HTTPError:
        pass

    headers = ["Job Title", "Company", "Match %", "Prep Topics", "Acceptance Chance %", "Status", "Date"]
    header_url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/A1:G1?valueInputOption=USER_ENTERED"
    body = json.dumps({"values": [headers]}).encode()
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(header_url, data=body, headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            })
            urllib.request.urlopen(req, timeout=30)
            return
        except Exception as e:
            log.warning("  Sheet header error (attempt %s/%s): %s", attempt, max_retries, e)
            time.sleep(attempt * 2)


def append_sheet_row(token: str, row: list, max_retries: int = 3) -> bool:
    import urllib.request, urllib.error
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/A:G:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
    body = json.dumps({"values": [row]}).encode()
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            })
            urllib.request.urlopen(req, timeout=30)
            return True
        except urllib.error.HTTPError as e:
            body_text = e.read().decode()[:200]
            if e.code in (429, 500, 502, 503) and attempt < max_retries:
                time.sleep(attempt * 5)
                continue
            log.error("  Sheet append error: %s %s", e.code, body_text)
            return False
        except urllib.error.URLError as e:
            if attempt < max_retries:
                time.sleep(attempt * 5)
                continue
            log.error("  Sheet network error: %s", e)
            return False
    return False


# ── Pipeline helpers ────────────────────────────────────────────

def load_json(path: str) -> list:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_json(path: str, data: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def sanitize_folder_name(s: str) -> str:
    s = re.sub(r'[^\w\s-]', '', s).strip().lower()
    return re.sub(r'[-\s]+', '_', s)[:60]


def load_cv(path: str = CV_FILE) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_progress(path: str = PROGRESS_FILE) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(path: str = PROGRESS_FILE, data: dict = None) -> None:
    if data is None:
        data = load_progress(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _detect_broken_scraper(name: str, jobs_found: int, health_data: dict) -> dict:
    if name not in health_data:
        health_data[name] = {
            "last_run": datetime.datetime.now().isoformat(),
            "jobs_found": jobs_found,
            "http_success_rate": 1.0,
            "consecutive_zero_jobs": 0,
            "healthy": True,
        }
    h = health_data[name]
    h["last_run"] = datetime.datetime.now().isoformat()
    if jobs_found == 0:
        h["consecutive_zero_jobs"] = h.get("consecutive_zero_jobs", 0) + 1
        if h["consecutive_zero_jobs"] >= HEALTH_CONSECUTIVE_ZERO_THRESHOLD:
            h["healthy"] = False
            log.warning("  WARNING: %s scraper may be BROKEN (zero jobs for %s+ runs)", name, HEALTH_CONSECUTIVE_ZERO_THRESHOLD)
    else:
        h["consecutive_zero_jobs"] = 0
        h["healthy"] = True
    h["jobs_found"] = jobs_found
    health_data[name] = h
    return health_data


def _load_health() -> dict:
    if os.path.exists(HEALTH_FILE):
        try:
            with open(HEALTH_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def _save_health(health: dict) -> None:
    with open(HEALTH_FILE, "w") as f:
        json.dump(health, f, indent=2)


def _print_separator(title: str) -> None:
    log.info("")
    log.info("%s", "=" * 55)
    log.info("%s", title)
    log.info("%s", "=" * 55)


def _print_scraper_summary(name: str, stats: dict, health: dict) -> None:
    h = health.get(name.lower(), {})
    status = "OK" if h.get("healthy", True) else "BROKEN"
    log.info("%s:", name)
    log.info("  Searches executed:       %s", stats.get("queries", 0))
    log.info("  Pages scraped:           %s", stats.get("pages_scraped", 0))
    log.info("  Jobs found:              %s", stats.get("jobs_found", 0))
    log.info("  Duplicates removed:      %s", stats.get("duplicates", 0))
    log.info("  Failed requests:         %s", stats.get("failed_requests", 0))
    log.info("  Early stopped searches:  %s", stats.get("early_stopped", 0))
    log.info("  Duration:                %.1fs", stats.get("total_duration", 0))
    log.info("  Health status:           %s", status)


# ── Resume generation ───────────────────────────────────────────

def _resume_fingerprint(job: Dict[str, Any]) -> str:
    """Create a fingerprint for resume reuse detection."""
    title = sanitize_folder_name(job.get("title", ""))
    category = sanitize_folder_name(job.get("category", ""))
    return f"{category}_{title}"


def _check_resume_reuse(
    job: Dict[str, Any],
    progress: Dict[str, Any],
    output_base: str,
) -> Optional[str]:
    """Check if a similar resume already exists and can be reused."""
    fp = _resume_fingerprint(job)
    if fp in progress:
        folder = progress[fp].get("folder", "")
        cv_path = os.path.join(output_base, folder, "tailored_cv.docx") if folder else ""
        if cv_path and os.path.exists(cv_path):
            log.info("  Reusing existing resume (same role/category)")
            return folder
    return None


def generate_for_job(job: Dict[str, Any], cv_text: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[int], str]:
    """Generate tailored CV, cover letter, prep topics, and acceptance chance."""
    profile = classify_job_profile(job)
    log.info("  Target profile: %s", profile)

    system_prompt = build_system_prompt(profile, cv_text)
    user_prompt = f"""TARGET JOB:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Category: {job.get('category', 'N/A')}

JOB DESCRIPTION:
{job.get('description', 'Not available')}

CANDIDATE'S ORIGINAL PROFILE (use ONLY this information, NEVER invent):
{cv_text}

Produce the 4 items for this role."""

    response = query_groq(system_prompt, user_prompt, model=GENERATION_MODEL)

    cv = extract_delimited(response, "TAILORED_CV")
    cl = extract_delimited(response, "COVER_LETTER")
    prep = extract_delimited(response, "INTERVIEW_PREP")
    chance = extract_delimited(response, "ACCEPTANCE_CHANCE")

    if not cv:
        cv = response
    if not cl:
        cl_prompt = build_cover_letter_prompt(profile, job, cv_text)
        cl = query_groq(cl_prompt, f"Write a cover letter for {job['title']} at {job['company']}.", model=GENERATION_MODEL)

    chance_num = extract_score(chance) if chance else 50

    # Quality review pass
    log.info("  Running quality review...")
    try:
        cv = review_and_improve(cv, job.get("title", ""), job.get("description", ""))
    except Exception as e:
        log.warning("  Quality review skipped: %s", e)

    return cv, cl, prep, chance_num, profile


# ── DOCX/PDF generation ─────────────────────────────────────────

from docx import Document
from docx.shared import Pt, Inches, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from fpdf import FPDF

SKILL_CATEGORIES = [
    "Data Analytics:", "Visualization & Reporting:",
    "AI / ML & GenAI:", "Other Skills:",
    "Programming:", "Agentic AI:", "SAP & ERP:",
    "Finance & Accounting:",
]

_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_DATE_PATTERN = re.compile(rf"{_MONTHS}\s+\d{{4}}\s*(?:[–—-]|to|–|—)\s*{_MONTHS}\s+\d{{4}}")
_BODY_FONT = "Calibri"
_HEADING_FONT = "Calibri"
_BODY_SIZE = Pt(10.5)
_HEADING_SIZE = Pt(13)
_CONTACT_SIZE = Pt(9)
_NAVY = RGBColor(0x1F, 0x3A, 0x5F)
_DARK_GRAY = RGBColor(0x55, 0x55, 0x55)


def save_docx(text: str, path: str) -> None:
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = _BODY_FONT
    style.font.size = _BODY_SIZE
    style.paragraph_format.space_after = Pt(2)
    style.paragraph_format.space_before = Pt(0)

    lines = _prepare_lines(text)
    _render_docx(doc, lines)
    doc.save(path)


def save_pdf(text: str, path: str) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_font("DejaVu", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    pdf.add_font("DejaVu", "B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    pdf.set_margins(20, 18, 20)
    _render_pdf(pdf, _prepare_lines(text))
    pdf.output(path)


def _prepare_lines(text: str) -> list:
    raw = text.strip().split("\n")
    return [l.strip() for l in raw if l.strip()]


def _which_section(line: str):
    u = line.strip().upper().rstrip(":")
    section_keywords = [
        ("PROFESSIONAL SUMMARY", "summary"),
        ("TECHNICAL SKILLS", "skills"),
        ("WORK EXPERIENCE", "work"),
        ("GITHUB PROJECTS", "projects"),
        ("EDUCATION", "education"),
        ("CERTIFICATIONS", "certs"),
    ]
    for kw, label in section_keywords:
        if u == kw or u.startswith(kw):
            if kw.startswith("PROFESSIONAL"):
                return "summary"
            if kw.startswith("TECHNICAL"):
                return "skills"
            if kw.startswith("WORK"):
                return "work"
            if kw.startswith("GITHUB"):
                return "projects"
            if kw.startswith("EDUCATION"):
                return "education"
            if kw.startswith("CERTIFICATION"):
                return "certs"
    return None


def _render_docx(doc: Document, lines: list) -> None:
    current_section = None
    for line in lines:
        sec = _which_section(line)
        if sec:
            p = doc.add_paragraph()
            run = p.add_run(line.upper())
            run.bold = True
            run.font.size = Pt(11)
            run.font.color.rgb = _NAVY
            run.font.name = _HEADING_FONT
            current_section = sec
            continue

        if current_section == "summary":
            p = doc.add_paragraph()
            p.add_run(line).font.size = Pt(10)
            continue

        if current_section == "skills":
            if any(line.upper().startswith(cat.rstrip(":").upper()) for cat in SKILL_CATEGORIES):
                p = doc.add_paragraph()
                run = p.add_run(line)
                run.bold = True
                run.font.size = Pt(10)
            elif line.startswith("-"):
                p = doc.add_paragraph(style='List Bullet')
                p.text = line.lstrip("- ").strip()
                p.style.font.size = Pt(9.5)
            continue

        if line.startswith("-"):
            p = doc.add_paragraph(style='List Bullet')
            p.text = line.lstrip("- ").strip()
        else:
            p = doc.add_paragraph()
            p.add_run(line).font.size = Pt(10)


def _render_pdf(pdf: FPDF, lines: list) -> None:
    lm = pdf.l_margin
    avail_w = pdf.w - lm - pdf.r_margin
    current_section = None

    for line in lines:
        sec = _which_section(line)
        if sec:
            pdf.set_font("DejaVu", "B", 11)
            pdf.set_text_color(0x1F, 0x3A, 0x5F)
            pdf.cell(avail_w, 7, line.upper(), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            current_section = sec
            continue

        if current_section == "summary":
            pdf.set_font("DejaVu", "", 9.5)
            pdf.multi_cell(avail_w, 5.5, line)
            continue

        if line.startswith("-"):
            pdf.set_font("DejaVu", "", 9)
            pdf.set_x(lm + 4)
            pdf.multi_cell(avail_w - 4, 5, line.lstrip("- ").strip())
        else:
            pdf.set_font("DejaVu", "", 9.5)
            pdf.multi_cell(avail_w, 5.5, line)


# ── Scraping phase ─────────────────────────────────────────────

def run_scraper_internal(scraper_module, name: str, job_age_hours: int) -> Tuple[List[Dict], int, Dict]:
    """Run a scraper module and merge results."""
    total_jobs = []
    total_new = 0
    scraper_stats = {}

    try:
        if hasattr(scraper_module, 'fetch_all') and callable(scraper_module.fetch_all):
            jobs = scraper_module.fetch_all(job_age_hours=job_age_hours)
        else:
            jobs = scraper_module.fetch_all()

        if jobs:
            added = scraper_module.merge_into_all_roles(jobs)
            total_jobs = jobs
            total_new = added
        else:
            total_jobs = []
            total_new = 0

        if hasattr(scraper_module, 'get_last_stats'):
            scraper_stats = scraper_module.get_last_stats()
    except Exception as e:
        log.error("  %s scraper failed: %s", name, e)
        return [], 0, scraper_stats

    return total_jobs, total_new, scraper_stats


def run_scraping_phase(parallel: bool, job_age_hours: int) -> Tuple[List[Dict], Dict, Dict]:
    """Run configured scrapers and return deduplicated jobs + stats."""
    _print_separator("SCRAPING PHASE")
    metrics.start_phase("scraping")

    all_jobs = []
    source_stats = {}
    health_data = _load_health()

    scraper_configs = []
    from config import WEBSITES
    if WEBSITES.get("naukri", True):
        scraper_configs.append((naukri_scraper, "Naukri"))
    if WEBSITES.get("indeed", True):
        scraper_configs.append((indeed_scraper, "Indeed"))
    if WEBSITES.get("linkedin", True):
        scraper_configs.append((linkedin_scraper, "LinkedIn"))

    if not scraper_configs:
        log.warning("No scrapers enabled in search_config.json")
        return [], source_stats, health_data

    log.info("Job age filter: %d hours", job_age_hours)

    if parallel and len(scraper_configs) > 1:
        log.info("Running scrapers in parallel mode...")
        with ThreadPoolExecutor(max_workers=len(scraper_configs)) as executor:
            futures = {}
            for mod, name in scraper_configs:
                future = executor.submit(run_scraper_internal, mod, name, job_age_hours)
                futures[future] = name

            for future in as_completed(futures):
                name = futures[future]
                try:
                    jobs, added, stats = future.result()
                    log.info("%s: %s jobs fetched, %s new", name, len(jobs), added)
                    source_stats[name.lower()] = stats
                    health_data = _detect_broken_scraper(name, len(jobs), health_data)
                    all_jobs.extend(jobs)
                except Exception as e:
                    log.error("  %s scraper failed: %s", name, e)
                    source_stats[name.lower()] = {}
                    health_data = _detect_broken_scraper(name, 0, health_data)
    else:
        for mod, name in scraper_configs:
            log.info("Fetching %s jobs...", name)
            jobs, added, stats = run_scraper_internal(mod, name, job_age_hours)
            log.info("%s: %s jobs fetched, %s new", name, len(jobs), added)
            source_stats[name.lower()] = stats
            health_data = _detect_broken_scraper(name, len(jobs), health_data)
            all_jobs.extend(jobs)

    _save_health(health_data)
    metrics.end_phase("scraping")

    return all_jobs, source_stats, health_data


def log_scraper_results(name: str, jobs: list, added: int) -> None:
    log.info("%s fetched %s jobs, %s new", name, len(jobs), added)


# ── Main ────────────────────────────────────────────────────────

def main():
    metrics.start_phase("total")

    # Parse CLI args
    parallel = "--parallel" in sys.argv
    only_mode = "--only" in sys.argv
    skip_scrape = "--skip-scrape" in sys.argv
    skip_score = "--skip-score" in sys.argv
    skip_generate = "--skip-generate" in sys.argv

    job_age_hours = 24

    all_fetched_jobs = []
    source_stats = {}
    health_data = {}

    # ── Phase 1: Scrape ─────────────────────────────────────────
    if not skip_scrape:
        all_fetched_jobs, source_stats, health_data = run_scraping_phase(parallel, job_age_hours)

        # Cross-platform dedup
        metrics.start_phase("dedup")
        dedup = Deduplicator()
        unique_jobs = []
        dup_count = 0
        for job in all_fetched_jobs:
            if dedup.is_duplicate(
                job.get("company", ""),
                job.get("title", ""),
                job.get("location", ""),
                job.get("url", ""),
            ):
                dup_count += 1
            else:
                unique_jobs.append(job)
        all_fetched_jobs = unique_jobs
        log.info("Cross-platform dedup: %s duplicates removed, %s unique jobs", dup_count, len(unique_jobs))
        metrics.end_phase("dedup")
        metrics.increment("total_fetched", len(all_fetched_jobs))
        metrics.increment("duplicates_removed", dup_count)
    else:
        log.info("Skipping scrape phase (--skip-scrape)")
        all_fetched_jobs = load_json(JOBS_JSON)

    # ── Phase 2: Filter blacklisted ─────────────────────────────
    metrics.start_phase("filter")
    from config import BLACKLIST
    filtered_jobs = []
    rejected_jobs = []
    blacklist_lower = [b.lower() for b in BLACKLIST]
    for job in all_fetched_jobs:
        company = (job.get("company") or "").lower()
        title = (job.get("title") or "").lower()
        is_blacklisted = any(b in company or b in title for b in blacklist_lower)
        if is_blacklisted:
            job["rejection_reason"] = "Blacklisted company/keyword"
            rejected_jobs.append(job)
        else:
            filtered_jobs.append(job)
    all_jobs = filtered_jobs
    log.info("Blacklist filter: %s rejected, %s kept", len(rejected_jobs), len(all_jobs))
    metrics.end_phase("filter")

    # ── Phase 3: Score ──────────────────────────────────────────
    if not skip_score:
        metrics.start_phase("scoring")
        _print_separator("SCORING PHASE")
        log.info("Running weighted auto-scorer...")
        try:
            added_scores = auto_scorer.score_all_unscored()
            log.info("Scored %s new jobs", added_scores)
            metrics.increment("jobs_scored", added_scores)
        except Exception as e:
            log.error("Auto-scorer failed: %s", e)
        metrics.end_phase("scoring")

    # ── Phase 4: Load scores & get recommended ──────────────────
    cv_text = load_cv(CV_FILE)
    scored = load_json(SCORE_CACHE)

    good = [r for r in scored if isinstance(r.get('score'), int) and r['score'] >= MIN_AI_SCORE]
    good.sort(key=lambda x: x['score'], reverse=True)

    metrics.increment("total_scored", len(scored))
    metrics.increment("recommended", len(good))

    _print_separator("RECOMMENDED JOBS")
    log.info("Jobs with score >= %s: %s total", MIN_AI_SCORE, len(good))
    log.info("%-3s %-6s %-18s %-40s %-22s", "#", "Score", "Category", "Job Title", "Company")
    log.info("%s", "-" * 90)
    for i, r in enumerate(good, 1):
        cat = r.get('category', 'N/A')[:16]
        title = r['title'][:38]
        company = r['company'][:20]
        log.info("%-3s %-4s/10 %-18s %-38s %-20s", i, r['score'], cat, title, company)
    log.info("%s", "-" * 90)

    if not good:
        log.info("No jobs above threshold. Exiting.")
        return

    # ── Phase 5: Generate resumes ───────────────────────────────
    if not skip_generate:
        _print_separator("GENERATION PHASE")

        log.info("Getting Google Sheets token...")
        sheets_token = None
        try:
            sheets_token = get_sheets_token()
            _ensure_sheet_headers(sheets_token)
        except Exception as e:
            log.warning("  Sheets auth failed: %s", e)

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        os.makedirs(OUTPUT_DATE_DIR, exist_ok=True)

        all_jobs_map = {}
        for job in load_json(JOBS_JSON):
            key = (job.get("title", ""), job.get("company", ""))
            all_jobs_map[key] = job

        progress = load_progress(PROGRESS_FILE)
        completed = 0
        failed = 0
        skipped = 0
        reused = 0
        sheet_uploads = 0
        sheet_failures = 0
        applied_jobs_report = []

        for i, r in enumerate(good, 1):
            key = (r["title"], r["company"])
            job = all_jobs_map.get(key)
            if not job:
                log.warning("[%s/%s] SKIP (no data): %s @ %s", i, len(good), r['title'], r['company'])
                skipped += 1
                continue

            job_key = sanitize_folder_name(f"{r['company']}_{r['title']}")
            if job_key in progress:
                log.info("[%s/%s] SKIP (already done): %s @ %s", i, len(good), r['title'], r['company'])
                skipped += 1
                continue

            # Check resume reuse
            reuse = _check_resume_reuse(job, progress, OUTPUT_DIR)
            if reuse:
                reused += 1
                progress[job_key] = {"status": "reused", "folder": reuse}
                save_progress(PROGRESS_FILE, progress)
                continue

            log.info("[%s/%s] (Score: %s/10) %s @ %s", i, len(good), r['score'], r['title'], r['company'])

            metrics.start_phase(f"gen_{i}")
            try:
                ok = False
                cv_result, cl_result, prep_result, chance_num, profile = generate_for_job(job, cv_text)
                if cv_result:
                    from docx import Document as DocxDoc
                    folder_name = sanitize_folder_name(f"{r['company']}_{r['title']}")
                    folder_path = os.path.join(OUTPUT_DATE_DIR, folder_name)
                    os.makedirs(folder_path, exist_ok=True)

                    save_docx(cv_result, os.path.join(folder_path, "tailored_cv.docx"))
                    save_pdf(cv_result, os.path.join(folder_path, "tailored_cv.pdf"))
                    if cl_result:
                        save_docx(cl_result, os.path.join(folder_path, "cover_letter.docx"))
                        save_pdf(cl_result, os.path.join(folder_path, "cover_letter.pdf"))

                    ok = True
                    completed += 1

                    # Sheets upload
                    if sheets_token:
                        match_pct = r['score'] * 10
                        today = datetime.date.today().strftime("%Y-%m-%d")
                        row = [
                            r['title'], r['company'], match_pct,
                            prep_result or "", chance_num or 50, "Applied", today,
                        ]
                        try:
                            if append_sheet_row(sheets_token, row):
                                sheet_uploads += 1
                            else:
                                sheet_failures += 1
                        except Exception as e:
                            log.error("  Sheet append failed: %s", e)
                            sheet_failures += 1

                    applied_jobs_report.append({
                        "title": r['title'],
                        "company": r['company'],
                        "location": job.get("location", ""),
                        "score": r['score'],
                        "profile": profile,
                        "match_pct": r['score'] * 10,
                        "folder": folder_name,
                    })
                    progress[job_key] = {"status": "done", "folder": folder_name}

            except Exception as e:
                log.error("  FAILED: %s", e)
                failed += 1

            metrics.end_phase(f"gen_{i}")
            save_progress(PROGRESS_FILE, progress)

        log.info("Generation complete: %s completed, %s reused, %s skipped, %s failed",
                 completed, reused, skipped, failed)

        write_applied_jobs(applied_jobs_report)

    # ── Phase 6: Reports ────────────────────────────────────────
    _print_separator("REPORTS")
    write_jobs_scraped(all_fetched_jobs)
    write_jobs_filtered(rejected_jobs)
    write_recommended_jobs(good)

    # Compute daily trend
    daily_trend = {}
    for job in all_fetched_jobs:
        d = job.get("date", datetime.date.today().isoformat())
        daily_trend[d] = daily_trend.get(d, 0) + 1

    # Top companies
    company_counts = {}
    for job in all_fetched_jobs:
        c = job.get("company", "Unknown")
        company_counts[c] = company_counts.get(c, 0) + 1
    top_companies = sorted(
        [{"name": k, "count": v} for k, v in company_counts.items()],
        key=lambda x: x["count"], reverse=True
    )[:15]

    # Top categories
    cat_counts = {}
    for job in all_fetched_jobs:
        cat = job.get("category", "Unknown")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    top_categories = sorted(
        [{"name": k, "count": v} for k, v in cat_counts.items()],
        key=lambda x: x["count"], reverse=True
    )

    dashboard_stats = {
        "date": datetime.date.today().isoformat(),
        "runtime_seconds": round(metrics.total_elapsed(), 1),
        "total_scraped": len(all_fetched_jobs),
        "total_recommended": len(good),
        "total_applied": len([j for j in load_json(PROGRESS_FILE).values() if j.get("status") == "done"]),
        "source_stats": source_stats,
        "daily_trend": daily_trend,
        "top_companies": top_companies,
        "top_categories": top_categories,
    }
    generate_dashboard(dashboard_stats)

    # ── Phase 7: Summary ────────────────────────────────────────
    _print_separator("SCRAPING SUMMARY")
    for name_key in ["naukri", "indeed", "linkedin"]:
        if name_key in source_stats:
            _print_scraper_summary(name_key.capitalize(), source_stats.get(name_key, {}), health_data)
        else:
            log.info("%s: (not fetched)", name_key.capitalize())

    _print_separator("TOTALS")
    all_jobs_count = len(load_json(JOBS_JSON))
    log.info("Jobs in database:         %s", all_jobs_count)
    log.info("Jobs scored:              %s", len(scored))
    if scored:
        avg = sum(r['score'] for r in scored) / len(scored)
        log.info("Average score:            %.1f/10", avg)
    log.info("Jobs above threshold:     %s", len(good))
    log.info("Applications generated:   %s", completed)

    metrics.print_summary()

    # Save agent stats
    stats_entry = {
        "date": datetime.date.today().isoformat(),
        "runtime_seconds": round(metrics.total_elapsed(), 1),
        "total_scraped": len(all_fetched_jobs),
        "total_scored": len(scored),
        "recommended": len(good),
        "sources": source_stats,
    }
    existing_stats = load_json(STATS_FILE)
    if not isinstance(existing_stats, list):
        existing_stats = [existing_stats] if existing_stats else []
    existing_stats.append(stats_entry)
    save_json(STATS_FILE, existing_stats)

    _print_separator("DONE")
    log.info("All reports in outputs/reports/")
    log.info("Dashboard: outputs/dashboard/index.html")
    log.info("Generated files: %s/", OUTPUT_DATE_DIR)


if __name__ == "__main__":
    main()
