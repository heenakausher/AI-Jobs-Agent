import json
import logging
import os
import re
import sys
import time
import urllib.request
import urllib.error
import datetime
from groq_api import query_groq
import naukri_scraper
import indeed_scraper
import linkedin_scraper
import auto_scorer

# ── Logging ──────────────────────────────────────────────────────────────
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
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from fpdf import FPDF

# ── Google Sheets ──────────────────────────────────────────────────────────────
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as AuthRequest

# ── Paths & config ─────────────────────────────────────────────────────────────
JOBS_JSON = "processed_jobs.json"
CV_FILE = "enhanced_cv.txt"
SCORE_CACHE = "score_cache.json"
PROGRESS_FILE = "generation_progress.json"
OUTPUT_DIR = "outputs"
CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"
SHEET_ID = "1debuNPIgf0hYPIaUyLy42IARIXaNE46Gxp9hB50Y8H0"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
MODEL = "llama-3.1-8b-instant"

OUTPUT_DATE_DIR = os.path.join(OUTPUT_DIR, datetime.date.today().strftime("%Y-%m-%d"))

# ── Groq prompts ───────────────────────────────────────────────────────────────
CUSTOMIZE_SYSTEM_PROMPT = """You are an expert ATS optimization specialist and career coach.

Your task is to produce 4 items for a job application. Return them with the exact delimiters shown.

STRICT RULES (violations will result in rejection):
1. Do NOT invent or fabricate any skills, experience, projects, certifications, titles, or achievements not in the candidate's profile.
2. Only rephrase, reorganize, restructure, de-emphasize, or emphasize information that already exists.
3. You may change section order to prioritize what is most relevant for the target role.
4. You may incorporate keywords from the job description ONLY where they genuinely match existing experience.
5. Keep all dates, company names, percentages, and factual data exactly as in the original.
6. For Agentic AI/ML roles: lead with AI skills + GitHub projects, then work experience.
7. For Data Analyst/BI roles: lead with work experience and data tools, then AI projects.
8. For Finance roles: lead with finance experience + education, then data analytics skills.

Use these delimiters and format exactly:

===TAILORED_CV===
Heena Kausher
kausher92@gmail.com | 7898680077 | www.github.com/heenakausher
www.linkedin.com/in/heena-kausher-90418a118 | www.mygreatlearning.com/eportfolio/heena-kausher

PROFESSIONAL SUMMARY
<2-3 sentence summary prioritising relevant experience for the target role>

TECHNICAL SKILLS
Data Analytics: SQL, SAP S4 HANA, SAP (SAC), Python, Pandas, NumPy
Visualization & Reporting: Tableau, Power BI, Advanced Excel, Advanced PowerPoint
AI / ML & GenAI:
Agentic AI / Multi-Agent Systems (CrewAI, LangGraph)
Large Language Models (Groq LLM, Llama, GPT)
...
Other Skills: Team Management, Financial Statements, FP&A, Budgeting, Projections, Accounting, Taxation

WORK EXPERIENCE
Abis Export India Pvt Ltd (Rajnandgaon, C.G.) — Sep 2021 – Nov 2025
Data Analyst
- Automated ad hoc and monthly reporting in Power BI for 12 segments, reducing manual work by 10 hours per week
...

GITHUB PROJECTS
Project 1: <title>
Technologies: <list>
- <bullet point>
...
GitHub: <url>

EDUCATION
- MBA - Banking & Finance, NMIMS CDOE | 67.33%
- M.Com - Pt. Ravishankar Shukla University | 46.50%
- B.Com - Pt. Ravishankar Shukla University | 60.44%

CERTIFICATIONS
- PGP in Data Science & Analytics - Great Lakes Executive Learning | GPA: 3.9
- Chartered Accountancy - IPCC (Group-1) | May 2012 |  52.75%
- Chartered Accountancy - CPT | Dec 2010 | 55.00%

===COVER_LETTER===
<professional cover letter, 250-400 words>

===INTERVIEW_PREP===
<comma-separated list of technical and behavioural topics to prepare for this role>

===ACCEPTANCE_CHANCE===
<number 0-100 representing estimated probability of acceptance"""


def sanitize_folder_name(s: str) -> str:
    s = re.sub(r'[^\w\s-]', '', s).strip().lower()
    s = re.sub(r'[-\s]+', '_', s)
    return s[:60]


def load_cv(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_scores(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_progress(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ── Google Sheets ───────────────────────────────────────────────────────────────

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
            return
        except urllib.error.HTTPError as e:
            body_text = e.read().decode()[:200]
            if e.code in (429, 500, 502, 503) and attempt < max_retries:
                wait = attempt * 5
                log.warning("  Sheet API error %s, retrying in %ss: %s", e.code, wait, body_text)
                time.sleep(wait)
                continue
            log.error("  Sheet append error: %s %s", e.code, body_text)
            return
        except urllib.error.URLError as e:
            if attempt < max_retries:
                wait = attempt * 5
                log.warning("  Sheet network error, retrying in %ss: %s", wait, e)
                time.sleep(wait)
                continue
            log.error("  Sheet network error: %s", e)
            return


# ── Groq generation ────────────────────────────────────────────────────────────

def generate_for_job(job: dict, cv_text: str) -> tuple:
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

    response = query_groq(CUSTOMIZE_SYSTEM_PROMPT, user_prompt, model=MODEL)

    def extract_delimiter(label: str) -> str:
        start = response.find(f"==={label}===")
        if start == -1:
            return ""
        start += len(f"==={label}===")
        remaining = ["TAILORED_CV", "COVER_LETTER", "INTERVIEW_PREP", "ACCEPTANCE_CHANCE"]
        end = len(response)
        for other in remaining:
            if other == label:
                continue
            pos = response.find(f"==={other}===", start)
            if pos != -1 and pos < end:
                end = pos
        return response[start:end].strip()

    cv = extract_delimiter("TAILORED_CV")
    cl = extract_delimiter("COVER_LETTER")
    prep = extract_delimiter("INTERVIEW_PREP")
    chance = extract_delimiter("ACCEPTANCE_CHANCE")

    if not cv:
        cv = response
    if not cl:
        cl = ""
    if not prep:
        prep = ""
    try:
        chance_num = int("".join(c for c in chance if c.isdigit()))
        chance_num = max(0, min(100, chance_num))
    except (ValueError, TypeError):
        chance_num = 50

    return cv, cl, prep, chance_num


# ── DOCX generation ────────────────────────────────────────────────────────────

def _set_keep_with_next(paragraph):
    pPr = paragraph._p.get_or_add_pPr()
    keepNext = OxmlElement('w:keepNext')
    pPr.append(keepNext)


def _add_section_heading(doc, text: str):
    p = doc.add_paragraph()
    p.space_before = Pt(14)
    p.space_after = Pt(6)
    run = p.add_run(text.upper())
    run.bold = True
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    run.font.name = "Calibri"
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '4')
    bottom.set(qn('w:color'), '1F3A5F')
    bottom.set(qn('w:space'), '1')
    pBdr.append(bottom)
    pPr.append(pBdr)
    _set_keep_with_next(p)


def _add_body(doc, text: str, bold: bool = False, size: int = 11, space_after: int = 3):
    p = doc.add_paragraph()
    p.space_after = Pt(space_after)
    p.space_before = Pt(0)
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.name = "Calibri"
    run.bold = bold
    return p


def _add_bullet(doc, text: str, size: int = 10.5):
    p = doc.add_paragraph(style='List Bullet')
    p.clear()
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.name = "Calibri"
    p.space_after = Pt(1)
    p.space_before = Pt(0)
    return p


# ── Skill category labels ─────────────────────────────────────────────────
SKILL_CATEGORIES = [
    "Data Analytics:", "Visualization & Reporting:",
    "AI / ML & GenAI:", "Other Skills:"
]

# ── Date pattern for company line detection ──────────────────────────────
_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_DATE_PATTERN = re.compile(
    rf"{_MONTHS}\s+\d{{4}}\s*(?:[–—-]|to|–|—)\s*{_MONTHS}\s+\d{{4}}"
)


def _split_skill_items(text: str) -> list:
    """Split comma-separated skill items, respecting parenthesised groups."""
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
    """Expand inline skill category lines into separate label + bullet items."""
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
    """Check if text contains a date range like 'Sep 2021 – Nov 2025'."""
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
    """Split combined contact line into 2 rows: email|phone|github and linkedin|greatlearning."""
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
    """Insert | before Month Year in certification lines: 'Name May 2012 | 55%' → 'Name | May 2012 | 55%'."""
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
    """Standardize Education and Certification section content."""
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
            # Split combined Chartered Accountancy line
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
    style.font.name = 'Calibri'
    style.font.size = Pt(10.5)
    style.paragraph_format.space_after = Pt(2)
    style.paragraph_format.space_before = Pt(0)

    section_keywords = [
        "PROFESSIONAL SUMMARY", "TECHNICAL SKILLS", "WORK EXPERIENCE",
        "GITHUB PROJECTS", "EDUCATION", "CERTIFICATIONS",
        "PROFESSIONAL SUMMARY:", "TECHNICAL SKILLS:", "WORK EXPERIENCE:",
        "GITHUB PROJECTS:", "EDUCATION:", "CERTIFICATIONS:"
    ]

    def which_section(line: str):
        u = line.strip().upper()
        for kw in section_keywords:
            if u.startswith(kw) or u == kw:
                k = kw.rstrip(":")
                if k.startswith("PROFESSIONAL"):
                    return "summary"
                if k.startswith("TECHNICAL"):
                    return "skills"
                if k.startswith("WORK"):
                    return "work"
                if k.startswith("GITHUB"):
                    return "projects"
                if k.startswith("EDUCATION"):
                    return "education"
                if k.startswith("CERTIFICATION"):
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
            run.font.size = Pt(16)
            run.font.name = "Calibri"
            run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
            name_done = True
            i += 1
            continue

        # Contact lines: only match before encountering any section heading
        if name_done and contact_lines < 2 and not which_section(line) and len(line) < 200:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.space_after = Pt(2) if contact_lines == 0 else Pt(6)
            run = p.add_run(line)
            run.font.size = Pt(9)
            run.font.name = "Calibri"
            run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            contact_lines += 1
            i += 1
            continue

        sec = which_section(line)
        if sec:
            _add_section_heading(doc, line.rstrip(":"))
            current_section = sec
            contact_lines = 2  # stop contact matching after first heading
            prev_was_company = False
            i += 1
            continue

        if current_section == "summary":
            _add_body(doc, line, size=10.5, space_after=3)
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
                run = p.add_run(matched_cat)
                run.bold = True
                run.font.size = Pt(10.5)
                run.font.name = "Calibri"
            else:
                txt = line.lstrip("-•* ").strip()
                if txt:
                    _add_bullet(doc, txt)
            i += 1
            continue

        if current_section == "work":
            clean = line.lstrip("-•* ").strip()
            if _has_date_range(clean) or _has_date_range(line):
                txt = clean.replace("**", "")
                p = doc.add_paragraph()
                p.space_before = Pt(10) if not prev_was_company else Pt(2)
                p.space_after = Pt(1)
                run = p.add_run(txt)
                run.bold = True
                run.font.size = Pt(10.5)
                run.font.name = "Calibri"
                _set_keep_with_next(p)
                prev_was_company = True
            elif _is_role_title(clean, prev_was_company) or _is_role_title(line, prev_was_company):
                txt = clean.replace("**", "").strip()
                p = _add_body(doc, txt, bold=True, size=10.5, space_after=2)
                _set_keep_with_next(p)
                prev_was_company = False
            else:
                txt = clean
                if txt:
                    _add_bullet(doc, txt)
                    prev_was_company = False
            i += 1
            continue

        if current_section == "projects":
            if line.startswith("Project ") and ":" in line:
                p = _add_body(doc, line, bold=True, size=10.5, space_after=2)
                _set_keep_with_next(p)
            elif line.startswith("Technologies:") or line.startswith("GitHub:"):
                _add_body(doc, line, bold=False, size=10.5, space_after=2)
            else:
                txt = line.lstrip("-•* ").strip()
                if txt:
                    _add_bullet(doc, txt)
            i += 1
            continue

        if current_section == "education":
            txt = line.lstrip("-•* ").strip()
            if txt:
                _add_bullet(doc, txt)
            i += 1
            continue

        if current_section == "certs":
            txt = line.lstrip("-•* ").strip()
            if txt:
                _add_bullet(doc, txt)
            i += 1
            continue

        if line.startswith("-") or line.startswith("•") or line.startswith("*"):
            txt = line.lstrip("-•* ").strip()
            if txt:
                _add_bullet(doc, txt)
        elif line.startswith("**") and line.endswith("**") and len(line) > 4:
            _add_body(doc, line.replace("**", ""), bold=True, size=10.5, space_after=3)
        else:
            _add_body(doc, line, size=10.5, space_after=3)
        i += 1

    doc.save(path)


# ── PDF generation ─────────────────────────────────────────────────────────────

def save_pdf(text: str, path: str):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_font("DejaVu", "", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    pdf.add_font("DejaVu", "B", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    pdf.set_margins(20, 20, 20)
    lm = pdf.l_margin
    avail_w = pdf.w - lm - pdf.r_margin

    section_keywords = [
        "PROFESSIONAL SUMMARY", "TECHNICAL SKILLS", "WORK EXPERIENCE",
        "GITHUB PROJECTS", "EDUCATION", "CERTIFICATIONS",
        "PROFESSIONAL SUMMARY:", "TECHNICAL SKILLS:", "WORK EXPERIENCE:",
        "GITHUB PROJECTS:", "EDUCATION:", "CERTIFICATIONS:"
    ]

    def which_section(line: str):
        u = line.strip().upper()
        for kw in section_keywords:
            if u.startswith(kw) or u == kw:
                k = kw.rstrip(":")
                if k.startswith("PROFESSIONAL"):
                    return "summary"
                if k.startswith("TECHNICAL"):
                    return "skills"
                if k.startswith("WORK"):
                    return "work"
                if k.startswith("GITHUB"):
                    return "projects"
                if k.startswith("EDUCATION"):
                    return "education"
                if k.startswith("CERTIFICATION"):
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

        # ── Name ─────────────────────────────────────────────────────
        if not name_done and line == "Heena Kausher":
            pdf.set_font("DejaVu", "B", 16)
            pdf.set_text_color(0x1F, 0x3A, 0x5F)
            pdf.cell(avail_w, 10, line, new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.set_text_color(0, 0, 0)
            name_done = True
            i += 1
            continue

        # ── Contact lines ───────────────────────────────────────────
        if name_done and contact_lines < 2 and len(line) < 200 and not which_section(line):
            pdf.set_font("DejaVu", "", 8)
            pdf.set_text_color(0x55, 0x55, 0x55)
            pdf.cell(avail_w, 6, line, new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2) if contact_lines == 1 else pdf.ln(0)
            contact_lines += 1
            i += 1
            continue

        # ── Section headings ────────────────────────────────────────
        sec = which_section(line)
        if sec:
            if pdf.h - pdf.b_margin - pdf.get_y() < 35:
                pdf.add_page()
            pdf.ln(2)
            pdf.set_font("DejaVu", "B", 11)
            pdf.set_text_color(0x1F, 0x3A, 0x5F)
            pdf.set_x(lm)
            pdf.cell(avail_w, 7, line.rstrip(":").upper(), new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(0x1F, 0x3A, 0x5F)
            pdf.set_line_width(0.3)
            y_line = pdf.get_y()
            pdf.line(lm, y_line, pdf.w - pdf.r_margin, y_line)
            pdf.ln(2)
            pdf.set_text_color(0, 0, 0)
            current_section = sec
            contact_lines = 2
            prev_was_company = False
            i += 1
            continue

        # ── PROFESSIONAL SUMMARY → Normal body ──────────────────────
        if current_section == "summary":
            pdf.set_font("DejaVu", "", 9.5)
            pdf.set_x(lm)
            try:
                pdf.multi_cell(avail_w, 5.5, line)
            except Exception:
                for word in line.split():
                    pdf.set_x(lm)
                    try:
                        pdf.multi_cell(avail_w, 5.5, word)
                    except Exception:
                        pass
            i += 1
            continue

        # ── TECHNICAL SKILLS ────────────────────────────────────────
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
                pdf.set_x(lm)
                pdf.cell(avail_w, 5.5, matched_cat, new_x="LMARGIN", new_y="NEXT")
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

        # ── WORK EXPERIENCE ─────────────────────────────────────────
        if current_section == "work":
            clean = line.lstrip("-•* ").strip()
            if _has_date_range(clean) or _has_date_range(line):
                txt = clean.replace("**", "")
                if pdf.h - pdf.b_margin - pdf.get_y() < 25:
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

        # ── GITHUB PROJECTS ─────────────────────────────────────────
        if current_section == "projects":
            if line.startswith("Project ") and ":" in line:
                if pdf.h - pdf.b_margin - pdf.get_y() < 20:
                    pdf.add_page()
                pdf.set_font("DejaVu", "B", 10)
                pdf.set_x(lm)
                pdf.cell(avail_w, 5.5, line, new_x="LMARGIN", new_y="NEXT")
            elif line.startswith("Technologies:") or line.startswith("GitHub:"):
                pdf.set_font("DejaVu", "", 9.5)
                pdf.set_x(lm)
                pdf.multi_cell(avail_w, 5.5, line)
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

        # ── EDUCATION → all as bullets ──────────────────────────────
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

        # ── CERTIFICATIONS → all as bullets ─────────────────────────
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

        # ── Fallback ────────────────────────────────────────────────
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
            try:
                pdf.multi_cell(avail_w, 5.5, line)
            except Exception:
                for word in line.split():
                    pdf.set_x(lm)
                    try:
                        pdf.multi_cell(avail_w, 5.5, word)
                    except Exception:
                        pass
        i += 1

    pdf.output(path)


# ── Output migration ──────────────────────────────────────────────────────────

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


# ── Job processing ─────────────────────────────────────────────────────────────

def process_job(job: dict, cv_text: str, output_base: str) -> tuple:
    company = job["company"]
    title = job["title"]
    folder_name = sanitize_folder_name(f"{company}_{title}")
    folder_path = os.path.join(output_base, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    log.info("  Generating CV + cover letter + prep info...")
    try:
        cv_text_tailored, cl_text, prep_text, chance_num = generate_for_job(job, cv_text)
    except Exception as e:
        log.error("  FAILED: %s", e)
        return False, None, None, None

    save_docx(cv_text_tailored, os.path.join(folder_path, "tailored_cv.docx"))
    save_pdf(cv_text_tailored, os.path.join(folder_path, "tailored_cv.pdf"))
    save_docx(cl_text, os.path.join(folder_path, "cover_letter.docx"))
    save_pdf(cl_text, os.path.join(folder_path, "cover_letter.pdf"))

    log.info("  OK -> %s/", folder_name)
    return True, prep_text, chance_num, folder_name


# ── Scraper helpers ─────────────────────────────────────────────────────────

def run_scraper_for_locations(scraper_module, name: str, pages: int = 2, locations: list = None):
    total_jobs = []
    total_new = 0
    if locations is None:
        locations = ["Hyderabad", "Pune"]
    for loc in locations:
        log.info("Fetching %s jobs from '%s'...", name, loc)
        added = 0
        try:
            jobs = scraper_module.fetch_all(location=loc, pages_per_search=pages)
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


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    timer_start()

    migrate_outputs_to_dated_dirs()

    locations = ["Hyderabad", "Pune"]
    for i, arg in enumerate(sys.argv):
        if arg == "--location" and i + 1 < len(sys.argv):
            locations = [sys.argv[i + 1]]

    any_fetch = False
    only_mode = False

    # ── Naukri ──────────────────────────────────────────────────────────
    if "--fetch-naukri" in sys.argv:
        any_fetch = True
        jobs, added = run_scraper_for_locations(naukri_scraper, "Naukri", locations=locations)
        log_scraper_results("Naukri", jobs, added)
        if "--only-naukri" in sys.argv:
            only_mode = True

    # ── Indeed ──────────────────────────────────────────────────────────
    if "--fetch-indeed" in sys.argv:
        any_fetch = True
        jobs, added = run_scraper_for_locations(indeed_scraper, "Indeed", locations=locations)
        log_scraper_results("Indeed", jobs, added)
        if "--only-indeed" in sys.argv:
            only_mode = True

    # ── LinkedIn ────────────────────────────────────────────────────────
    if "--fetch-linkedin" in sys.argv:
        any_fetch = True
        jobs, added = run_scraper_for_locations(linkedin_scraper, "LinkedIn", locations=locations)
        log_scraper_results("LinkedIn", jobs, added)
        if "--only-linkedin" in sys.argv:
            only_mode = True

    if any_fetch and only_mode:
        log.info("Only-mode set. Exiting after fetch.")
        log.info("Execution time: %s", timer_elapsed())
        return

    if any_fetch and not only_mode:
        log.info("Continuing with full pipeline...\n")

    # ── Auto-score ──────────────────────────────────────────────────────
    if "--auto-score" in sys.argv:
        log.info("Running auto-scorer on unscored jobs...")
        try:
            added_scores = auto_scorer.score_all_unscored()
            log.info("Auto-scored %s new jobs.", added_scores)
        except Exception as e:
            log.error("Auto-scorer failed: %s", e)

    cv_text = load_cv(CV_FILE)
    log.info("CV loaded (%s chars)", len(cv_text))

    scored = load_scores(SCORE_CACHE)
    log.info("Loaded %s cached scores", len(scored))

    good = [r for r in scored if isinstance(r['score'], int) and r['score'] > 6]
    good.sort(key=lambda x: x['score'], reverse=True)

    log.info("=" * 80)
    log.info("RECOMMENDED JOBS (score > 6): %s total", len(good))
    log.info("%-3s %-5s %-16s %-40s %-22s", "#", "Score", "Category", "Job Title", "Company")
    log.info("%s", "-" * 86)
    for i, r in enumerate(good, 1):
        cat = r.get('category', 'N/A')[:14]
        log.info("%-3s %-3s/10 %-16s %-37s %-20s", i, r['score'], cat, r['title'][:37], r['company'][:20])
    log.info("%s", "-" * 86)
    log.info("=" * 80)

    # ── Google Sheets auth ──────────────────────────────────────────────
    log.info("Getting Google Sheets token...")
    sheets_token = None
    try:
        sheets_token = get_sheets_token()
        log.info("  Sheets token ready.")
    except Exception as e:
        log.warning("  Sheets auth failed (will skip uploads): %s", e)

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
                    append_sheet_row(sheets_token, row)
                except Exception as e:
                    log.error("  Failed to append sheet row: %s", e)
            else:
                log.warning("  Skipping sheet append (no token).")
            progress[job_key] = {"status": "done"}
            completed += 1
        else:
            failed += 1

        save_progress(PROGRESS_FILE, progress)
        print()

    elapsed = timer_elapsed()
    log.info("=" * 80)
    log.info("FINAL SUMMARY")
    log.info("  Jobs scored:      %s", len(scored))
    log.info("  Jobs to process:  %s", len(good))
    log.info("  CVs generated:    %s", completed)
    log.info("  Cover letters:    %s", completed)
    log.info("  Skipped (done):   %s", skipped)
    log.info("  Failed:           %s", failed)
    log.info("  Sheets uploads:   %s", completed if sheets_token else 0)
    log.info("  Execution time:   %s", elapsed)
    log.info("  Output dir:       %s/", OUTPUT_DATE_DIR)
    log.info("=" * 80)


if __name__ == "__main__":
    main()
