import json
import logging
import os
import re
import sys
import time
import urllib.request
import urllib.error
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from groq_api import query_groq
import naukri_scraper
import indeed_scraper
import linkedin_scraper
import auto_scorer
from prompts import (
    detect_profile, build_system_prompt,
    build_cover_letter_prompt, extract_delimited, extract_score,
    PROFILES
)
from resume_reviewer import review_and_improve
from config import (
    CITIES, MIN_AI_SCORE, OUTPUT_DIR, JOBS_JSON, CV_FILE,
    SCORE_CACHE, PROGRESS_FILE, STATS_FILE, HEALTH_FILE,
    CLIENT_SECRET_FILE, TOKEN_FILE, SHEET_ID, SCOPES,
    GENERATION_MODEL, OUTPUT_DATE_DIR, CONCURRENT_WORKERS,
    HEALTH_CONSECUTIVE_ZERO_THRESHOLD, MAX_PAGES,
    LAST_RUN_FILE, JOB_AGE_DAYS_FIRST, JOB_AGE_DAYS_SUBSEQUENT
)

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

_start_time = None

def timer_start():
    global _start_time
    _start_time = time.time()

def timer_elapsed() -> str:
    if _start_time is None:
        return "0s"
    elapsed = time.time() - _start_time
    if elapsed < 60:
        return f"{elapsed:.1f}s"
    return f"{elapsed // 60:.0f}m {elapsed % 60:.0f}s"

def timer_elapsed_seconds() -> float:
    if _start_time is None:
        return 0.0
    return time.time() - _start_time

def load_last_run() -> int:
    if os.path.exists(LAST_RUN_FILE):
        try:
            with open(LAST_RUN_FILE, "r") as f:
                data = json.load(f)
            last = datetime.datetime.fromisoformat(data.get("last_run", ""))
            hours_since = (datetime.datetime.now() - last).total_seconds() / 3600
            if hours_since < 24:
                return JOB_AGE_DAYS_SUBSEQUENT
        except (json.JSONDecodeError, ValueError, TypeError, OSError):
            pass
    return JOB_AGE_DAYS_FIRST

def save_last_run():
    try:
        with open(LAST_RUN_FILE, "w") as f:
            json.dump({"last_run": datetime.datetime.now().isoformat()}, f)
    except OSError as e:
        log.warning("  Failed to save last_run.json: %s", e)

from docx import Document
from docx.shared import Pt, Inches, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from fpdf import FPDF

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as AuthRequest


def sanitize_folder_name(s: str) -> str:
    s = re.sub(r'[^\w\s-]', '', s).strip().lower()
    s = re.sub(r'[-\s]+', '_', s)
    return s[:60]


def load_cv(path: str = CV_FILE) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_scores(path: str = SCORE_CACHE) -> list:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def load_progress(path: str = PROGRESS_FILE) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(path: str = PROGRESS_FILE, data: dict = None):
    if data is None:
        data = load_progress(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_sheets_token() -> str:
    if not os.path.exists(TOKEN_FILE):
        log.error("No token.json found. Run first:")
        log.error("  python3 auth_sheets.py step1")
        log.error("  Then retry.")
        sys.exit(1)

    with open(TOKEN_FILE) as f:
        tok = json.load(f)

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
            req = urllib.request.Request(
                header_url, data=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
            )
            urllib.request.urlopen(req, timeout=30)
            log.info("  Sheet headers added.")
            return
        except Exception as e:
            log.warning("  Sheet header error (attempt %s/%s): %s", attempt, max_retries, e)
            time.sleep(attempt * 2)


def append_sheet_row(token: str, row: list, max_retries: int = 3):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/A:G:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS"
    body = json.dumps({"values": [row]}).encode()
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
            )
            urllib.request.urlopen(req, timeout=30)
            log.info("  Sheet row appended.")
            return True
        except urllib.error.HTTPError as e:
            body_text = e.read().decode()[:200]
            if e.code in (429, 500, 502, 503) and attempt < max_retries:
                wait = attempt * 5
                log.warning("  Sheet API error %s, retrying in %ss: %s", e.code, wait, body_text)
                time.sleep(wait)
                continue
            log.error("  Sheet append error: %s %s", e.code, body_text)
            return False
        except urllib.error.URLError as e:
            if attempt < max_retries:
                wait = attempt * 5
                log.warning("  Sheet network error, retrying in %ss: %s", wait, e)
                time.sleep(wait)
                continue
            log.error("  Sheet network error: %s", e)
            return False


def generate_for_job(job: dict, cv_text: str) -> tuple:
    profile = detect_profile(
        job.get('title', ''),
        job.get('description', ''),
        job.get('category', '')
    )
    log.info("  Detected profile: %s", profile)

    system_prompt = build_system_prompt(profile, cv_text)
    user_prompt = f"""TARGET JOB:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Category: {job.get('category', 'N/A')}

JOB DESCRIPTION:
{job.get('description', 'Not available')}

CANDIDATE'S ORIGINAL PROFILE (use ONLY this information):
{cv_text}

Produce the 4 items (tailored CV, cover letter, interview prep topics, acceptance chance) for this role."""

    response = query_groq(system_prompt, user_prompt, model=GENERATION_MODEL)

    cv = extract_delimited(response, "TAILORED_CV")
    cl = extract_delimited(response, "COVER_LETTER")
    prep = extract_delimited(response, "INTERVIEW_PREP")
    chance = extract_delimited(response, "ACCEPTANCE_CHANCE")

    if not cv:
        cv = response
    if not cl:
        log.info("  Cover letter not found in response, generating separately...")
        cl_prompt = build_cover_letter_prompt(profile, job, cv_text)
        cl = query_groq(cl_prompt, f"Write a cover letter for {job['title']} at {job['company']}.", model=GENERATION_MODEL)

    try:
        chance_num = extract_score(chance)
    except (ValueError, TypeError):
        chance_num = 50

    return cv, cl, prep, chance_num, profile


SKILL_CATEGORIES = [
    "Data Analytics:", "Visualization & Reporting:",
    "AI / ML & GenAI:", "Other Skills:",
    "Programming:", "Agentic AI:", "SAP & ERP:",
    "Finance & Accounting:"
]

_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_DATE_PATTERN = re.compile(
    rf"{_MONTHS}\s+\d{{4}}\s*(?:[–—-]|to|–|—)\s*{_MONTHS}\s+\d{{4}}"
)
_BODY_FONT = "Calibri"
_HEADING_FONT = "Calibri"
_BODY_SIZE = Pt(11)
_HEADING_SIZE = Pt(14)
_SUBHEADING_SIZE = Pt(12)
_CONTACT_SIZE = Pt(9)
_SECTION_HEADING_SIZE = Pt(13)
_NAVY = RGBColor(0x1F, 0x3A, 0x5F)
_DARK_GRAY = RGBColor(0x55, 0x55, 0x55)


def _set_keep_with_next(paragraph):
    pPr = paragraph._p.get_or_add_pPr()
    keepNext = OxmlElement('w:keepNext')
    pPr.append(keepNext)


def _add_section_heading(doc, text: str):
    p = doc.add_paragraph()
    p.space_before = Pt(16)
    p.space_after = Pt(6)
    run = p.add_run(text.upper())
    run.bold = True
    run.font.size = _SECTION_HEADING_SIZE
    run.font.color.rgb = _NAVY
    run.font.name = _HEADING_FONT
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:color'), '1F3A5F')
    bottom.set(qn('w:space'), '2')
    pBdr.append(bottom)
    pPr.append(pBdr)
    _set_keep_with_next(p)


def _add_body(doc, text: str, bold: bool = False, size=None, space_after: int = 4, alignment=None, color=None):
    if size is None:
        size = _BODY_SIZE
    p = doc.add_paragraph()
    p.space_after = Pt(space_after)
    p.space_before = Pt(0)
    if alignment:
        p.alignment = alignment
    run = p.add_run(text)
    run.font.size = size
    run.font.name = _BODY_FONT
    run.bold = bold
    if color:
        run.font.color.rgb = color
    return p


def _add_bullet(doc, text: str, size=None):
    if size is None:
        size = _BODY_SIZE
    p = doc.add_paragraph(style='List Bullet')
    p.clear()
    run = p.add_run(text)
    run.font.size = size
    run.font.name = _BODY_FONT
    p.space_after = Pt(1)
    p.space_before = Pt(0)
    p.paragraph_format.left_indent = Inches(0.25)
    return p


def _split_skill_items(text: str) -> list:
    items = []
    depth = 0
    buf = []
    for ch in text:
        if ch == '(':
            depth += 1
            buf.append(ch)
        elif ch == ')':
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == ',' and depth == 0:
            items.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        items.append(''.join(buf).strip())
    return [i for i in items if i]


def _expand_skill_categories(lines: list) -> list:
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        matching_cat = None
        for cat in SKILL_CATEGORIES:
            upper = stripped.upper()
            cat_key = cat.rstrip(":").upper()
            if upper.startswith(cat_key) and (len(stripped) == len(cat_key) or stripped[len(cat_key):].lstrip().startswith(":")):
                matching_cat = cat
                break
        if matching_cat:
            label = matching_cat
            rest = stripped[len(label.rstrip(":")):].lstrip(": ")
            if rest:
                items = _split_skill_items(rest)
                result.append(label)
                for item in items:
                    result.append("- " + item)
            else:
                result.append(line)
        else:
            result.append(line)
        i += 1
    return result


def _has_date_range(text: str) -> bool:
    return bool(_DATE_PATTERN.search(text))


def _is_role_title(text: str, prev_was_company: bool) -> bool:
    known = ["Data Analyst", "Tax Officer", "Accountant",
             "AI Engineer", "Analyst", "Executive"]
    t = text.strip()
    if not t:
        return False
    if t in known:
        return True
    for k in known:
        if t.startswith(k):
            return True
    if prev_was_company and len(t) < 60 and not t.startswith("-") and not t.startswith("•"):
        return True
    return False


def _split_contact(lines: list) -> list:
    result = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "Heena Kausher" and i + 1 < len(lines):
            result.append(line)
            contact_line = lines[i + 1].strip()
            parts = [p.strip() for p in contact_line.split("|")]
            row1, row2 = [], []
            for p in parts:
                pl = p.lower()
                if "linkedin" in pl:
                    row2.append(p)
                elif "greatlearning" in pl or "eportfolio" in pl:
                    row2.append(p)
                elif "github" in pl:
                    row1.append(p)
                elif "@" in p:
                    row1.append(p)
                elif sum(c.isdigit() for c in p) >= 6:
                    row1.append(p)
                else:
                    row1.append(p)
            if row1:
                result.append(" | ".join(row1))
            if row2:
                result.append(" | ".join(row2))
            result.extend(lines[i + 2:])
            return result
    return lines


def _add_date_sep(txt: str) -> str:
    m = re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{4}\b', txt)
    if m:
        idx = m.start()
        before = txt[:idx].rstrip()
        if not before.endswith("|"):
            after = txt[m.end():].lstrip("| ")
            if after:
                txt = before + " | " + m.group(0) + " | " + after
            else:
                txt = before + " | " + m.group(0)
    return txt


def _normalize_edu_cert(lines: list) -> list:
    result = []
    in_edu = False
    in_certs = False
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("EDUCATION"):
            in_edu = True
            in_certs = False
            result.append(line)
            continue
        if stripped.upper().startswith("CERTIFICATION"):
            in_edu = False
            in_certs = True
            result.append(line)
            continue
        if stripped.upper().startswith(("PROFESSIONAL SUMMARY", "TECHNICAL SKILLS", "WORK EXPERIENCE", "GITHUB PROJECTS")):
            in_edu = False
            in_certs = False
            result.append(line)
            continue
        if in_edu or in_certs:
            txt = stripped.lstrip("-•* ").strip()
            if not txt:
                continue
            txt = txt.replace("\u2013", "-").replace("\u2014", "-")
            if in_certs and "Chartered Accountancy" in txt and "CPT" in txt:
                parts = txt.split(";")
                for pi, pt in enumerate(parts):
                    pt = pt.strip()
                    if pt:
                        if pi > 0:
                            pt = "Chartered Accountancy - " + pt
                        pt = _add_date_sep(pt) if in_certs else pt
                        if "CPT" in pt and "Dec 2010" in pt and "55" not in pt:
                            pt = pt.rstrip(" |") + " | 55.00%"
                        result.append(pt)
                continue
            if in_edu:
                if "-" not in txt:
                    txt = txt.replace(", ", " - ", 1)
            if in_certs:
                txt = _add_date_sep(txt)
            result.append(txt)
        else:
            result.append(line)
    return result


def save_docx(text: str, path: str):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = _BODY_FONT
    style.font.size = _BODY_SIZE
    style.paragraph_format.space_after = Pt(2)
    style.paragraph_format.space_before = Pt(0)

    section_keywords = [
        "PROFESSIONAL SUMMARY", "TECHNICAL SKILLS", "WORK EXPERIENCE",
        "GITHUB PROJECTS", "EDUCATION", "CERTIFICATIONS",
    ]

    def which_section(line: str):
        u = line.strip().upper().rstrip(":")
        for kw in section_keywords:
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

    current_section = None
    prev_was_company = False

    raw_lines = text.strip().split("\n")
    lines = _split_contact(raw_lines)
    lines = _normalize_edu_cert(lines)
    lines = _expand_skill_categories(lines)

    i = 0
    name_done = False
    contact_lines = 0

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if not name_done and line == "Heena Kausher":
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.space_after = Pt(2)
            run = p.add_run(line)
            run.bold = True
            run.font.size = Pt(20)
            run.font.name = _HEADING_FONT
            run.font.color.rgb = _NAVY
            name_done = True
            i += 1
            continue

        if name_done and contact_lines < 2 and not which_section(line) and len(line) < 200:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.space_after = Pt(2) if contact_lines == 0 else Pt(8)
            run = p.add_run(line)
            run.font.size = _CONTACT_SIZE
            run.font.name = _BODY_FONT
            run.font.color.rgb = _DARK_GRAY
            contact_lines += 1
            i += 1
            continue

        sec = which_section(line)
        if sec:
            _add_section_heading(doc, line.rstrip(":"))
            current_section = sec
            contact_lines = 2
            prev_was_company = False
            i += 1
            continue

        if current_section == "summary":
            _add_body(doc, line, size=Pt(10.5), space_after=4)
            i += 1
            continue

        if current_section == "skills":
            matched_cat = None
            for cat in SKILL_CATEGORIES:
                if line.upper().startswith(cat.rstrip(":").upper()) and (
                    len(line) == len(cat.rstrip(":")) or line[len(cat.rstrip(":"))] == ":"
                ):
                    matched_cat = cat
                    break
            if matched_cat:
                p = doc.add_paragraph()
                p.space_after = Pt(2)
                p.space_before = Pt(6)
                run = p.add_run(matched_cat)
                run.bold = True
                run.font.size = Pt(10.5)
                run.font.name = _BODY_FONT
                run.font.color.rgb = _NAVY
            else:
                txt = line.lstrip("-•* ").strip()
                if txt:
                    _add_bullet(doc, txt, size=Pt(10))
            i += 1
            continue

        if current_section == "work":
            clean = line.lstrip("-•* ").strip()
            if _has_date_range(clean) or _has_date_range(line):
                txt = clean.replace("**", "")
                p = doc.add_paragraph()
                p.space_before = Pt(12) if not prev_was_company else Pt(2)
                p.space_after = Pt(1)
                run = p.add_run(txt)
                run.bold = True
                run.font.size = Pt(10.5)
                run.font.name = _BODY_FONT
                _set_keep_with_next(p)
                prev_was_company = True
            elif _is_role_title(clean, prev_was_company) or _is_role_title(line, prev_was_company):
                txt = clean.replace("**", "").strip()
                p = _add_body(doc, txt, bold=True, size=Pt(10.5), space_after=2)
                _set_keep_with_next(p)
                prev_was_company = False
            else:
                txt = clean
                if txt:
                    _add_bullet(doc, txt, size=Pt(10))
                    prev_was_company = False
            i += 1
            continue

        if current_section == "projects":
            if line.startswith("Project ") and ":" in line:
                p = _add_body(doc, line, bold=True, size=Pt(10.5), space_after=2)
                _set_keep_with_next(p)
            elif line.startswith("Technologies:") or line.startswith("GitHub:"):
                _add_body(doc, line, size=Pt(10), space_after=2)
            else:
                txt = line.lstrip("-•* ").strip()
                if txt:
                    _add_bullet(doc, txt, size=Pt(10))
            i += 1
            continue

        if current_section == "education":
            txt = line.lstrip("-•* ").strip()
            if txt:
                _add_bullet(doc, txt, size=Pt(10))
            i += 1
            continue

        if current_section == "certs":
            txt = line.lstrip("-•* ").strip()
            if txt:
                _add_bullet(doc, txt, size=Pt(10))
            i += 1
            continue

        if line.startswith("-") or line.startswith("•") or line.startswith("*"):
            txt = line.lstrip("-•* ").strip()
            if txt:
                _add_bullet(doc, txt, size=Pt(10))
        elif line.startswith("**") and line.endswith("**") and len(line) > 4:
            _add_body(doc, line.replace("**", ""), bold=True, size=_BODY_SIZE, space_after=3)
        else:
            _add_body(doc, line, size=Pt(10.5), space_after=3)
        i += 1

    doc.save(path)


def save_pdf(text: str, path: str):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_font("DejaVu", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    pdf.add_font("DejaVu", "B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    pdf.set_margins(20, 18, 20)
    lm = pdf.l_margin
    avail_w = pdf.w - lm - pdf.r_margin

    section_keywords = [
        "PROFESSIONAL SUMMARY", "TECHNICAL SKILLS", "WORK EXPERIENCE",
        "GITHUB PROJECTS", "EDUCATION", "CERTIFICATIONS",
    ]

    def which_section(line: str):
        u = line.strip().upper().rstrip(":")
        for kw in section_keywords:
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

    current_section = None
    prev_was_company = False

    raw_lines = text.strip().split("\n")
    lines = _split_contact(raw_lines)
    lines = _normalize_edu_cert(lines)
    lines = _expand_skill_categories(lines)

    i = 0
    name_done = False
    contact_lines = 0

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if not name_done and line == "Heena Kausher":
            pdf.set_font("DejaVu", "B", 18)
            pdf.set_text_color(0x1F, 0x3A, 0x5F)
            pdf.cell(avail_w, 11, line, new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.set_text_color(0, 0, 0)
            name_done = True
            i += 1
            continue

        if name_done and contact_lines < 2 and len(line) < 200 and not which_section(line):
            pdf.set_font("DejaVu", "", 8)
            pdf.set_text_color(0x55, 0x55, 0x55)
            pdf.cell(avail_w, 5.5, line, new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.set_text_color(0, 0, 0)
            if contact_lines == 1:
                pdf.ln(3)
            contact_lines += 1
            i += 1
            continue

        sec = which_section(line)
        if sec:
            if pdf.h - pdf.b_margin - pdf.get_y() < 40:
                pdf.add_page()
            pdf.ln(3)
            pdf.set_font("DejaVu", "B", 12)
            pdf.set_text_color(0x1F, 0x3A, 0x5F)
            pdf.set_x(lm)
            pdf.cell(avail_w, 7, line.rstrip(":").upper(), new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(0x1F, 0x3A, 0x5F)
            pdf.set_line_width(0.4)
            y_line = pdf.get_y()
            pdf.line(lm, y_line, pdf.w - pdf.r_margin, y_line)
            pdf.ln(2)
            pdf.set_text_color(0, 0, 0)
            current_section = sec
            contact_lines = 2
            prev_was_company = False
            i += 1
            continue

        if current_section == "summary":
            pdf.set_font("DejaVu", "", 9.5)
            pdf.set_x(lm)
            pdf.multi_cell(avail_w, 5.5, line)
            i += 1
            continue

        if current_section == "skills":
            matched_cat = None
            for cat in SKILL_CATEGORIES:
                if line.upper().startswith(cat.rstrip(":").upper()) and (
                    len(line) == len(cat.rstrip(":")) or line[len(cat.rstrip(":"))] == ":"
                ):
                    matched_cat = cat
                    break
            if matched_cat:
                pdf.set_font("DejaVu", "B", 10)
                pdf.set_text_color(0x1F, 0x3A, 0x5F)
                pdf.set_x(lm)
                pdf.cell(avail_w, 5.5, matched_cat, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
            else:
                txt = line.lstrip("-•* ").strip()
                if txt:
                    pdf.set_font("DejaVu", "", 9.5)
                    pdf.set_x(lm)
                    bullet_w = pdf.get_string_width("• ") + 2
                    if avail_w - bullet_w > 20:
                        pdf.cell(bullet_w, 5.5, "• ")
                        pdf.multi_cell(avail_w - bullet_w, 5.5, txt)
            i += 1
            continue

        if current_section == "work":
            clean = line.lstrip("-•* ").strip()
            if _has_date_range(clean) or _has_date_range(line):
                txt = clean.replace("**", "")
                if pdf.h - pdf.b_margin - pdf.get_y() < 30:
                    pdf.add_page()
                pdf.ln(1) if not prev_was_company else pdf.ln(0)
                pdf.set_font("DejaVu", "B", 10)
                pdf.set_x(lm)
                pdf.cell(avail_w, 6, txt, new_x="LMARGIN", new_y="NEXT")
                prev_was_company = True
            elif _is_role_title(clean, prev_was_company) or _is_role_title(line, prev_was_company):
                txt = clean.replace("**", "").strip()
                pdf.set_font("DejaVu", "B", 10)
                pdf.set_x(lm)
                pdf.cell(avail_w, 5.5, txt, new_x="LMARGIN", new_y="NEXT")
                prev_was_company = False
            else:
                txt = clean
                if txt:
                    pdf.set_font("DejaVu", "", 9.5)
                    pdf.set_x(lm)
                    bullet_w = pdf.get_string_width("• ") + 2
                    if avail_w - bullet_w > 20:
                        pdf.cell(bullet_w, 5.5, "• ")
                        pdf.multi_cell(avail_w - bullet_w, 5.5, txt)
                    prev_was_company = False
            i += 1
            continue

        if current_section == "projects":
            if line.startswith("Project ") and ":" in line:
                if pdf.h - pdf.b_margin - pdf.get_y() < 25:
                    pdf.add_page()
                pdf.set_font("DejaVu", "B", 10)
                pdf.set_x(lm)
                pdf.cell(avail_w, 5.5, line, new_x="LMARGIN", new_y="NEXT")
            elif line.startswith("Technologies:") or line.startswith("GitHub:"):
                pdf.set_font("DejaVu", "", 9)
                pdf.set_text_color(0x55, 0x55, 0x55)
                pdf.set_x(lm)
                pdf.multi_cell(avail_w, 5, line)
                pdf.set_text_color(0, 0, 0)
            else:
                txt = line.lstrip("-•* ").strip()
                if txt:
                    pdf.set_font("DejaVu", "", 9.5)
                    pdf.set_x(lm)
                    bullet_w = pdf.get_string_width("• ") + 2
                    if avail_w - bullet_w > 20:
                        pdf.cell(bullet_w, 5.5, "• ")
                        pdf.multi_cell(avail_w - bullet_w, 5.5, txt)
            i += 1
            continue

        if current_section == "education":
            txt = line.lstrip("-•* ").strip()
            if txt:
                pdf.set_font("DejaVu", "", 9.5)
                pdf.set_x(lm)
                bullet_w = pdf.get_string_width("• ") + 2
                if avail_w - bullet_w > 20:
                    pdf.cell(bullet_w, 5.5, "• ")
                    pdf.multi_cell(avail_w - bullet_w, 5.5, txt)
            i += 1
            continue

        if current_section == "certs":
            txt = line.lstrip("-•* ").strip()
            if txt:
                pdf.set_font("DejaVu", "", 9.5)
                pdf.set_x(lm)
                bullet_w = pdf.get_string_width("• ") + 2
                if avail_w - bullet_w > 20:
                    pdf.cell(bullet_w, 5.5, "• ")
                    pdf.multi_cell(avail_w - bullet_w, 5.5, txt)
            i += 1
            continue

        if line.startswith("-") or line.startswith("•") or line.startswith("*"):
            txt = line.lstrip("-•* ").strip()
            if txt:
                pdf.set_font("DejaVu", "", 9.5)
                pdf.set_x(lm)
                bullet_w = pdf.get_string_width("• ") + 2
                if avail_w - bullet_w > 20:
                    pdf.cell(bullet_w, 5.5, "• ")
                    pdf.multi_cell(avail_w - bullet_w, 5.5, txt)
        elif line.startswith("**") and line.endswith("**") and len(line) > 4:
            pdf.set_font("DejaVu", "B", 10)
            pdf.set_x(lm)
            pdf.cell(avail_w, 5.5, line.replace("**", ""), new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("DejaVu", "", 9.5)
            pdf.set_x(lm)
            pdf.multi_cell(avail_w, 5.5, line)
        i += 1

    pdf.output(path)


def migrate_outputs_to_dated_dirs():
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if not os.path.isdir(OUTPUT_DIR):
        return
    for name in os.listdir(OUTPUT_DIR):
        path = os.path.join(OUTPUT_DIR, name)
        if not os.path.isdir(path) or date_pattern.match(name):
            continue
        if name.startswith("."):
            continue
        mtime = os.path.getmtime(path)
        date_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        target = os.path.join(OUTPUT_DIR, date_str, name)
        parent = os.path.dirname(target)
        os.makedirs(parent, exist_ok=True)
        if not os.path.exists(target):
            os.rename(path, target)
            log.info("  Moved outputs/%s -> outputs/%s/%s", name, date_str, name)
        else:
            log.warning("  Skip move outputs/%s -> %s (target exists)", name, target)


def process_job(job: dict, cv_text: str, output_base: str) -> tuple:
    company = job["company"]
    title = job["title"]
    folder_name = sanitize_folder_name(f"{company}_{title}")
    folder_path = os.path.join(output_base, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    log.info("  Generating CV + cover letter + prep info...")
    try:
        cv_text_tailored, cl_text, prep_text, chance_num, profile = generate_for_job(job, cv_text)
    except Exception as e:
        log.error("  FAILED: %s", e)
        return False, None, None, None

    log.info("  Running quality review pass...")
    try:
        cv_text_tailored = review_and_improve(
            cv_text_tailored,
            job.get('title', ''),
            job.get('description', '')
        )
    except Exception as e:
        log.warning("  Quality review skipped: %s", e)

    save_docx(cv_text_tailored, os.path.join(folder_path, "tailored_cv.docx"))
    save_pdf(cv_text_tailored, os.path.join(folder_path, "tailored_cv.pdf"))
    save_docx(cl_text, os.path.join(folder_path, "cover_letter.docx"))
    save_pdf(cl_text, os.path.join(folder_path, "cover_letter.pdf"))

    log.info("  OK -> %s/", folder_name)
    return True, prep_text, chance_num, folder_name


def _detect_broken_scraper(name: str, jobs_found: int, health_data: dict):
    """Check if a scraper is returning zero jobs and flag it."""
    if name not in health_data:
        health_data[name] = {
            "last_run": datetime.datetime.now().isoformat(),
            "jobs_found": jobs_found,
            "http_success_rate": 1.0,
            "avg_response_time": 0.0,
            "consecutive_zero_jobs": 0,
            "healthy": True,
        }

    h = health_data[name]
    h["last_run"] = datetime.datetime.now().isoformat()

    if jobs_found == 0:
        h["consecutive_zero_jobs"] = h.get("consecutive_zero_jobs", 0) + 1
        log.warning("  WARNING: %s scraper returned zero jobs (%s consecutive)",
                     name, h["consecutive_zero_jobs"])
        if h["consecutive_zero_jobs"] >= HEALTH_CONSECUTIVE_ZERO_THRESHOLD:
            h["healthy"] = False
            log.warning("  WARNING: %s scraper may be BROKEN (zero jobs for %s+ consecutive runs)",
                         name, HEALTH_CONSECUTIVE_ZERO_THRESHOLD)
    else:
        h["consecutive_zero_jobs"] = 0
        h["healthy"] = True

    h["jobs_found"] = jobs_found
    health_data[name] = h
    return health_data


def _save_agent_stats(stats: dict):
    existing = []
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                existing = json.load(f)
                if not isinstance(existing, list):
                    existing = [existing]
        except (json.JSONDecodeError, TypeError):
            existing = []

    existing.append(stats)
    with open(STATS_FILE, "w") as f:
        json.dump(existing, f, indent=2)


def _load_health():
    if os.path.exists(HEALTH_FILE):
        try:
            with open(HEALTH_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def _save_health(health: dict):
    with open(HEALTH_FILE, "w") as f:
        json.dump(health, f, indent=2)


def _print_separator(title: str):
    log.info("")
    log.info("%s", "=" * 50)
    log.info("%s", title)
    log.info("%s", "=" * 50)


def _print_scraper_summary(name: str, stats: dict, health: dict):
    avg_resp = 0.0
    durations = stats.get("durations", [])
    if durations:
        avg_resp = sum(durations) / len(durations)

    h = health.get(name.lower(), {})
    status = "OK" if h.get("healthy", True) else "BROKEN"

    log.info("%s:", name)
    log.info("  Total search queries executed:  %s", stats.get("queries", 0))
    log.info("  Total pages scraped:            %s", stats.get("pages", 0))
    log.info("  Total jobs found:               %s", stats.get("jobs_found", 0))
    log.info("  Duplicate jobs removed:         %s", stats.get("duplicates", 0))
    log.info("  New jobs added:                 %s", stats.get("new_jobs", 0))
    log.info("  Early stopped searches:         %s", stats.get("early_stopped", 0))
    log.info("  Failed requests:                %s", stats.get("failed_requests", 0))
    log.info("  Average response time:          %.2fs", avg_resp)
    log.info("  Total runtime:                  %.1fs", stats.get("total_duration", 0))
    log.info("  Health status:                  %s", status)

    if stats.get("jobs_found", 0) == 0:
        log.info("  WARNING: %s scraper returned zero jobs", name)


def run_scraper_internal(scraper_module, name: str, pages: int = None, location: str = None, job_age: int = 7) -> tuple:
    total_jobs = []
    total_new = 0
    scraper_stats = {}

    try:
        if hasattr(scraper_module, 'fetch_all') and callable(scraper_module.fetch_all):
            if location:
                jobs = scraper_module.fetch_all(location=location, pages_per_search=pages, job_age=job_age)
            else:
                jobs = scraper_module.fetch_all(pages_per_search=pages, job_age=job_age)
        else:
            jobs = scraper_module.fetch_all(location=location or CITIES[0], pages_per_search=pages or MAX_PAGES)

        if jobs:
            save_path = JOBS_JSON
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


def run_scraper_for_locations(scraper_module, name: str, pages: int = 2, locations: list = None):
    """Backward-compatible scraper runner."""
    total_jobs = []
    total_new = 0
    if locations is None:
        locations = ["Hyderabad", "Pune"]
    for loc in locations:
        log.info("Fetching %s jobs from '%s'...", name, loc)
        try:
            if hasattr(scraper_module, 'fetch_all'):
                jobs = scraper_module.fetch_all(location=loc, pages_per_search=pages)
            else:
                jobs = scraper_module.fetch_all(location=loc)
            if jobs:
                scraper_module.save_jobs(jobs)
                added = scraper_module.merge_into_all_roles(jobs)
                total_jobs.extend(jobs)
                total_new += added
            else:
                jobs = []
            log.info("  %s: %s jobs, %s new", loc, len(jobs), added)
        except Exception as e:
            log.error("  %s scraper failed for %s: %s", name, loc, e)
    return total_jobs, total_new


def log_scraper_results(name: str, jobs: list, added: int):
    log.info("=" * 80)
    log.info("Fetched %s total jobs from %s, %s new.", len(jobs), name, added)
    if added > 0:
        for j in jobs[-10:]:
            log.info("  %s @ %s [%s]", j["title"], j["company"], j.get("category", "N/A"))


def main():
    timer_start()

    migrate_outputs_to_dated_dirs()

    locations = CITIES[:]
    for i, arg in enumerate(sys.argv):
        if arg == "--location" and i + 1 < len(sys.argv):
            locations = [sys.argv[i + 1]]

    pages_arg = MAX_PAGES
    for i, arg in enumerate(sys.argv):
        if arg == "--pages" and i + 1 < len(sys.argv):
            try:
                pages_arg = int(sys.argv[i + 1])
            except ValueError:
                pass

    job_age = load_last_run()
    log.info("Job age filter: %s days (first run: %sd, subsequent: %sd)",
             job_age, JOB_AGE_DAYS_FIRST, JOB_AGE_DAYS_SUBSEQUENT)

    any_fetch = False
    only_mode = False
    parallel = "--parallel" in sys.argv

    source_stats = {}
    health_data = _load_health()

    scraper_configs = []
    if "--fetch-naukri" in sys.argv:
        scraper_configs.append((naukri_scraper, "Naukri", pages_arg, locations))
        any_fetch = True
        if "--only-naukri" in sys.argv:
            only_mode = True
    if "--fetch-indeed" in sys.argv:
        scraper_configs.append((indeed_scraper, "Indeed", pages_arg, locations))
        any_fetch = True
        if "--only-indeed" in sys.argv:
            only_mode = True
    if "--fetch-linkedin" in sys.argv:
        scraper_configs.append((linkedin_scraper, "LinkedIn", pages_arg, locations))
        any_fetch = True
        if "--only-linkedin" in sys.argv:
            only_mode = True

    if any_fetch:
        _print_separator("SCRAPING PHASE")

        if parallel and len(scraper_configs) > 1:
            log.info("Running scrapers in parallel (--parallel mode)...")
            with ThreadPoolExecutor(max_workers=len(scraper_configs)) as executor:
                futures = {}
                for mod, name, pages, locs in scraper_configs:
                    loc_arg = locs[0] if len(locs) == 1 else None
                    future = executor.submit(run_scraper_internal, mod, name, pages, loc_arg, job_age)
                    futures[future] = name

                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        jobs, added, stats = future.result()
                        log_scraper_results(name, jobs, added)
                        source_stats[name.lower()] = stats
                        health_data = _detect_broken_scraper(name, len(jobs), health_data)
                    except Exception as e:
                        log.error("  %s scraper failed: %s", name, e)
                        source_stats[name.lower()] = {}
                        health_data = _detect_broken_scraper(name, 0, health_data)
        else:
            for mod, name, pages, locs in scraper_configs:
                if len(locs) > 0:
                    log.info("Fetching %s jobs (single location mode: %s)...", name, locs[0])
                    jobs, added, stats = run_scraper_internal(mod, name, pages, locs[0] if len(locs) == 1 else None, job_age)
                else:
                    jobs, added, stats = run_scraper_internal(mod, name, pages, job_age=job_age)
                log_scraper_results(name, jobs, added)
                source_stats[name.lower()] = stats
                health_data = _detect_broken_scraper(name, len(jobs), health_data)

        _save_health(health_data)

        save_last_run()

        if any_fetch and only_mode:
            _print_separator("SCRAPING SUMMARY")
            for name_key in ["naukri", "indeed", "linkedin"]:
                if name_key in source_stats:
                    _print_scraper_summary(name_key.capitalize(), source_stats.get(name_key, {}), health_data)

            elapsed = timer_elapsed()
            log.info("%s", "=" * 50)
            log.info("Total execution time: %s", elapsed)
            return

    if any_fetch and not only_mode:
        log.info("Continuing with full pipeline...\n")

    jobs_scored_this_run = 0
    if "--auto-score" in sys.argv:
        _print_separator("SCORING PHASE")
        log.info("Running auto-scorer on unscored jobs...")
        try:
            added_scores = auto_scorer.score_all_unscored()
            jobs_scored_this_run = added_scores
            log.info("Auto-scored %s new jobs.", added_scores)
        except Exception as e:
            log.error("Auto-scorer failed: %s", e)

    cv_text = load_cv(CV_FILE)
    log.info("CV loaded (%s chars)", len(cv_text))

    scored = load_scores(SCORE_CACHE)
    log.info("Loaded %s cached scores", len(scored))

    good = [r for r in scored if isinstance(r['score'], int) and r['score'] > MIN_AI_SCORE]
    good.sort(key=lambda x: x['score'], reverse=True)

    _print_separator("RECOMMENDED JOBS")
    log.info("Jobs with score > %s: %s total", MIN_AI_SCORE, len(good))
    log.info("%-3s %-5s %-16s %-40s %-22s", "#", "Score", "Category", "Job Title", "Company")
    log.info("%s", "-" * 86)
    for i, r in enumerate(good, 1):
        cat = r.get('category', 'N/A')[:14]
        log.info("%-3s %-3s/10 %-16s %-37s %-20s", i, r['score'], cat, r['title'][:37], r['company'][:20])
    log.info("%s", "-" * 86)

    log.info("Getting Google Sheets token...")
    sheets_token = None
    try:
        sheets_token = get_sheets_token()
        log.info("  Sheets token ready.")
        _ensure_sheet_headers(sheets_token)
    except Exception as e:
        log.warning("  Sheets auth failed (will skip uploads): %s", e)

    _print_separator("GENERATION PHASE")
    log.info("Generating tailored CVs & cover letters for %s jobs...", len(good))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DATE_DIR, exist_ok=True)

    with open(JOBS_JSON, "r", encoding="utf-8") as f:
        all_jobs = json.load(f)

    job_map = {}
    for job in all_jobs:
        key = (job.get("title", ""), job.get("company", ""))
        job_map[key] = job

    progress = load_progress(PROGRESS_FILE)
    completed = 0
    failed = 0
    skipped = 0
    sheet_uploads = 0
    sheet_failures = 0

    for i, r in enumerate(good, 1):
        key = (r["title"], r["company"])
        job = job_map.get(key)
        if not job:
            log.warning("[%s/%s] SKIP (no data): %s @ %s", i, len(good), r['title'], r['company'])
            skipped += 1
            continue

        job_key = sanitize_folder_name(f"{r['company']}_{r['title']}")
        if job_key in progress:
            log.info("[%s/%s] SKIP (already done): (%s) %s @ %s", i, len(good), r['category'], r['title'], r['company'])
            skipped += 1
            continue

        log.info("[%s/%s] (%s) %s @ %s [Score: %s/10]", i, len(good), r['category'], r['title'], r['company'], r['score'])
        try:
            ok, prep_text, chance_num, _ = process_job(job, cv_text, OUTPUT_DATE_DIR)
        except Exception as e:
            log.error("  UNEXPECTED ERROR: %s", e)
            ok = False
            prep_text = None
            chance_num = None

        if ok:
            match_pct = r['score'] * 10
            today = datetime.date.today().strftime("%Y-%m-%d")
            row = [
                r['title'],
                r['company'],
                match_pct,
                prep_text if prep_text else "",
                chance_num if chance_num else 50,
                "Applied",
                today
            ]
            log.info("  Appending to Google Sheet...")
            if sheets_token:
                try:
                    if append_sheet_row(sheets_token, row):
                        sheet_uploads += 1
                    else:
                        sheet_failures += 1
                except Exception as e:
                    log.error("  Failed to append sheet row: %s", e)
                    sheet_failures += 1
            else:
                log.warning("  Skipping sheet append (no token).")
            progress[job_key] = {"status": "done"}
            completed += 1
        else:
            failed += 1

        save_progress(PROGRESS_FILE, progress)
        print()

    elapsed_str = timer_elapsed()
    elapsed_sec = timer_elapsed_seconds()

    _print_separator("SCRAPING SUMMARY")
    for name_key in ["naukri", "indeed", "linkedin"]:
        if name_key in source_stats:
            _print_scraper_summary(name_key.capitalize(), source_stats.get(name_key, {}), health_data)
        else:
            log.info("%s: (not fetched)", name_key.capitalize())

    _print_separator("PROCESSING SUMMARY")
    log.info("Total jobs in database:      %s", len(all_jobs))
    log.info("Jobs scored:                 %s", len(scored))
    log.info("Average score:               %.1f/10", sum(r['score'] for r in scored) / len(scored) if scored else 0)
    log.info("Jobs above threshold (%s+):   %s", MIN_AI_SCORE, len(good))
    log.info("CVs generated:               %s", completed)
    log.info("Cover letters generated:     %s", completed)
    log.info("Google Sheets rows uploaded: %s", sheet_uploads)
    log.info("Skipped (already done):      %s", skipped)
    log.info("Failed:                      %s", failed)
    log.info("Total execution time:        %s", elapsed_str)
    log.info("Output directory:            %s/", OUTPUT_DATE_DIR)

    _print_separator("WHERE TIME WAS SPENT")
    total_elapsed = timer_elapsed_seconds()
    log.info("%-20s %12s %12s", "Phase", "Duration", "% of Total")
    log.info("%s", "-" * 46)
    scrape_total = 0.0
    for name_key in ["naukri", "indeed", "linkedin"]:
        sd = source_stats.get(name_key, {})
        dur = sd.get("total_duration", 0) if isinstance(sd, dict) else 0
        scrape_total += dur
        pct = (dur / total_elapsed * 100) if total_elapsed > 0 else 0
        log.info("%-20s %8.1fs %10.1f%%", name_key.capitalize() + " scrape", dur, pct)
    gen_dur = max(0, total_elapsed - scrape_total)
    gen_pct = (gen_dur / total_elapsed * 100) if total_elapsed > 0 else 0
    log.info("%-20s %8.1fs %10.1f%%", "Scoring + generation", gen_dur, gen_pct)
    log.info("-" * 46)
    log.info("%-20s %8.1fs %10.1f%%", "TOTAL", total_elapsed, 100.0)
    log.info("%s", "=" * 50)

    # ── Save agent_stats.json ──────────────────────────────────────
    total_jobs_found = sum(
        source_stats.get(s, {}).get("jobs_found", 0)
        for s in ["naukri", "indeed", "linkedin"]
    )
    total_duplicates = sum(
        source_stats.get(s, {}).get("duplicates", 0)
        for s in ["naukri", "indeed", "linkedin"]
    )
    total_queries = sum(
        source_stats.get(s, {}).get("queries", 0)
        for s in ["naukri", "indeed", "linkedin"]
    )
    total_early_stopped = sum(
        source_stats.get(s, {}).get("early_stopped", 0)
        for s in ["naukri", "indeed", "linkedin"]
    )

    stats_entry = {
        "date": datetime.date.today().isoformat(),
        "runtime_seconds": round(elapsed_sec, 1),
        "job_age_days": job_age,
        "naukri": source_stats.get("naukri", {}),
        "indeed": source_stats.get("indeed", {}),
        "linkedin": source_stats.get("linkedin", {}),
        "total": {
            "queries": total_queries,
            "jobs_found": total_jobs_found,
            "duplicates": total_duplicates,
            "early_stopped": total_early_stopped,
            "new_jobs": sum(
                source_stats.get(s, {}).get("new_jobs", 0)
                for s in ["naukri", "indeed", "linkedin"]
            ),
            "jobs_scored": jobs_scored_this_run,
            "recommended": len(good),
            "cv_generated": completed,
            "cover_letters": completed,
            "uploaded_to_sheet": sheet_uploads,
            "failed_uploads": sheet_failures,
        },
    }
    _save_agent_stats(stats_entry)


if __name__ == "__main__":
    main()
