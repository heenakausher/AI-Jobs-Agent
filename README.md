# AI Jobs Agent

AI-powered job application assistant that scrapes jobs from Naukri, Indeed, and LinkedIn, scores them using Groq, and generates recruiter-quality, ATS-optimized tailored resumes and cover letters — fully automated via GitHub Actions.

> **Generates professional, role-specific resumes** for Data Analyst, BI Analyst, Financial Analyst, SAP FICO, AI Engineer, Agentic AI Engineer, ML Engineer, and GenAI/LLM roles.

---

## Features

- **Multi-source job scraping** — Naukri (API), Indeed (HTML), LinkedIn (public job search)
- **AI-powered scoring** — Groq LLM evaluates each job against your CV (0-10)
- **Profile-specific resume generation** — Different resume strategies for 8+ role types
- **ATS-optimized output** — No tables, text boxes, icons, graphics, columns, or headers/footers with important info
- **Professional formatting** — Calibri typography, consistent spacing, proper margins
- **DOCX + PDF output** — Matching visual formatting across both formats
- **Quality review pass** — LLM review catches grammar, tone, ATS issues, hallucinations
- **Cover letters** — Personalized 300-450 word cover letters per role
- **Google Sheets integration** — Tracks applications with match %, prep topics, acceptance chance
- **Deduplication** — Never regenerates already-processed jobs
- **Cached scoring** — `score_cache.json` and `generation_progress.json` persist across runs
- **Date-stamped outputs** — Organized under `outputs/YYYY-MM-DD/`
- **GitHub Actions automation** — Daily scheduled runs with artifact uploads

---

## Architecture

```mermaid
flowchart TD
    A[Job Scrapers] --> B[processed_jobs.json]
    B --> C[Groq Scoring]
    C --> D{Score > 6?}
    D -->|Yes| E[Profile Detection]
    E --> F[Profile-Specific Resume Generation]
    F --> G[Quality Review Pass]
    G --> H[DOCX Generation]
    G --> I[PDF Generation]
    F --> J[Cover Letter Generation]
    J --> K[DOCX Generation]
    J --> L[PDF Generation]
    H --> M[Google Sheets Upload]
    I --> M
    K --> M
    L --> M
    M --> N[GitHub Artifacts]
    
    style A fill:#e1f5fe
    style B fill:#fff3e0
    style C fill:#e8f5e9
    style E fill:#f3e5f5
    style F fill:#e8f5e9
    style G fill:#fff3e0
    style H fill:#fce4ec
    style I fill:#fce4ec
    style J fill:#f3e5f5
    style M fill:#e1f5fe
    style N fill:#e8f5e9
```

---

## Project Structure

```
AI-Jobs-Agent/
├── main.py                      # Orchestrator: scraping, scoring, generation, upload
├── groq_api.py                  # Groq LLM API client with retry & rate-limit handling
├── prompts.py                   # Profile-specific resume/cover letter prompts (8+ profiles)
├── resume_reviewer.py           # Quality review pass for generated resumes
├── auto_scorer.py               # Automated AI job scoring against CV
├── auth_sheets.py               # Google Sheets OAuth2 flow
│
├── naukri_scraper.py            # Naukri.com job scraper (API v3)
├── indeed_scraper.py            # Indeed.com job scraper (HTML parsing)
├── linkedin_scraper.py          # LinkedIn job scraper (guest API)
│
├── reformat_cv.py               # Utility to reformat existing CVs with new styling
├── deploy.sh                    # Local deployment & run script
├── requirements.txt             # Python dependencies
│
├── processed_jobs.json          # Central job store (all sources merged)
├── score_cache.json             # Cached job scores (persisted across runs)
├── generation_progress.json     # Tracks which jobs already generated CVs/letters
├── enhanced_cv.txt              # Source CV text (used as factual base)
│
├── .github/workflows/
│   └── daily-agent.yml          # GitHub Actions automation
│
└── outputs/
    └── YYYY-MM-DD/              # Date-stamped generated files
        └── company_title/
            ├── tailored_cv.docx
            ├── tailored_cv.pdf
            ├── cover_letter.docx
            └── cover_letter.pdf
```

---

## Workflow

### 1. Job Scraping
Scrapers collect jobs from Naukri, Indeed, and LinkedIn for target locations (Hyderabad, Pune) across these roles:
- Data Analyst, Business Analyst, Business Intelligence
- Financial Analyst, Finance, SAP FICO
- AI Engineer, Agentic AI, Machine Learning, AI Intern
- GenAI, LLM, RAG

All jobs merge into `processed_jobs.json`.

### 2. AI Scoring
Each job is scored against the candidate's CV using Groq LLM (`llama-3.3-70b-versatile`):
- **0-10 scale** based on skills match, experience relevance, education alignment
- Only jobs scoring **> 6** proceed to generation
- Results cached in `score_cache.json`

### 3. Profile Detection
The system detects the best-matching resume profile from the job title, category, and description:
- Data Analyst, BI Analyst, Financial Analyst, SAP FICO
- AI Engineer, Agentic AI Engineer, ML Engineer, GenAI/LLM

### 4. Resume Generation
Each profile uses a different prompt strategy:
- **Analyst roles** → Lead with work experience + data tools, then AI projects
- **AI/ML roles** → Lead with AI skills + GitHub projects, then work experience
- **Finance roles** → Lead with finance experience + education, then analytics skills

### 5. Quality Review
Every generated resume passes through a second LLM review that verifies:
- Grammar, spelling, punctuation
- Professional tone
- ATS keyword coverage
- Hallucinations (fabricated information)
- Duplicate content
- Weak bullet points
- Action verb usage

### 6. Output Generation
- **DOCX** — python-docx with Calibri font, professional navy headings, consistent spacing
- **PDF** — fpdf2 with matching DejaVu font, same visual structure

### 7. Google Sheets Upload
Application data logged with: job title, company, match %, prep topics, acceptance chance, status, date.

### 8. GitHub Actions Artifacts
Generated files uploaded as workflow artifacts for download.

---

## Installation

### Requirements
- Python 3.10+
- Groq API Key
- Google Sheets OAuth credentials (optional)

### Python Dependencies
```bash
pip install -r requirements.txt
```

### System Fonts (PDF generation)
```bash
# Debian/Ubuntu
sudo apt-get install fonts-dejavu-core

# macOS — DejaVu fonts are pre-installed
```

---

## Configuration

### 1. Environment Variables
```env
GROQ_API_KEY=gsk_your_groq_api_key
```

### 2. Candidate CV
Create `enhanced_cv.txt` containing your resume in plain text. This is the **sole source of factual information** — nothing will be fabricated.

### 3. Profile-Specific Templates
The system supports these resume profiles in `prompts.py`:
| Profile | Focus | Skill Priority |
|---------|-------|---------------|
| Data Analyst | Analytics, dashboards, SQL | Data Analytics → Viz → AI |
| BI Analyst | BI tools, dashboards, reporting | Viz → Data Analytics → AI |
| Financial Analyst | FP&A, budgeting, forecasting | Finance → Data Analytics → Viz |
| SAP FICO | SAP, FICO, financial systems | SAP → Finance → Data Analytics |
| AI Engineer | LLMs, RAG, LangChain | AI → Programming → Data |
| Agentic AI Engineer | Agents, CrewAI, orchestration | AI → Agentic → Programming |
| ML Engineer | ML, Python, scikit-learn | AI → Programming → Data |
| GenAI/LLM Engineer | Generative AI, RAG, prompts | AI → Programming → Data |

### 4. Google Sheets Setup
```bash
# Step 1: Generate auth URL
python3 auth_sheets.py step1

# Step 2: Visit the URL, authorize, paste the redirect URL
python3 auth_sheets.py step2 "<redirect_url>"
```

---

## GitHub Secrets

| Secret | Description |
|--------|-------------|
| `GROQ_API_KEY` | Your Groq API key (e.g., `gsk_...`) |
| `GOOGLE_CLIENT_SECRET_BASE64` | `base64 client_secret.json` |
| `GOOGLE_TOKEN_JSON_BASE64` | `base64 token.json` |
| `CV_TEXT_BASE64` | `base64 enhanced_cv.txt` |

### Setting up secrets
```bash
# Encode files to base64
base64 -w0 client_secret.json > client_secret_base64.txt
base64 -w0 token.json > token_base64.txt
base64 -w0 enhanced_cv.txt > cv_base64.txt

# Copy the contents into GitHub Secrets (Settings → Secrets → Actions)
cat client_secret_base64.txt
cat token_base64.txt
cat cv_base64.txt
```

---

## Usage

### Local Run
```bash
# Full pipeline: fetch + score + generate
python3 main.py --fetch-naukri --fetch-indeed --fetch-linkedin --auto-score

# Or run individual steps:
python3 main.py --fetch-naukri --only-naukri      # Fetch only
python3 auto_scorer.py                              # Score only
python3 main.py                                     # Generate only
```

### Deploy Script
```bash
bash deploy.sh --setup    # One-time setup (venv, deps, fonts)
bash deploy.sh --run      # Run the full agent
```

---

## GitHub Actions Automation

The workflow runs **daily at 03:00 UTC** and can also be triggered manually.

### Workflow Steps
1. Checkout repository
2. Setup Python 3.10
3. Install DejaVu fonts (PDF generation)
4. Install Python dependencies
5. Restore cached scores + progress
6. Decode Google OAuth credentials from secrets
7. Decode CV text from secrets
8. Scrape Naukri, Indeed, LinkedIn jobs (each continues on error)
9. Auto-score new jobs with Groq
10. Generate tailored CVs + cover letters
11. Quality review pass
12. Upload to Google Sheets
13. Save updated cache
14. Upload generated files as artifacts
15. Commit cache files back to repository

### Caching Strategy
- `score_cache.json` — persists scored jobs across workflow runs
- `generation_progress.json` — prevents regenerating CVs for already-processed jobs
- Both restored from GitHub Actions cache; committed back after each run

---

## Output Structure

```
outputs/
└── 2026-06-26/
    ├── accenture_data_analyst/
    │   ├── tailored_cv.docx      # ATS-optimized resume (DOCX)
    │   ├── tailored_cv.pdf       # ATS-optimized resume (PDF)
    │   ├── cover_letter.docx     # Personalized cover letter (DOCX)
    │   └── cover_letter.pdf      # Personalized cover letter (PDF)
    ├── google_ai_engineer/
    │   └── ...
    └── ...
```

### ATS Compliance
- ✅ No tables, text boxes, icons, or graphics
- ✅ No columns or headers/footers with important info
- ✅ Standard section headings (PROFESSIONAL SUMMARY, TECHNICAL SKILLS, etc.)
- ✅ Professional fonts (Calibri body, navy headings)
- ✅ Consistent spacing and bullet formatting
- ✅ Compatible with Workday, Greenhouse, Lever, and Taleo

---

## Hallucination Prevention

The system uses multiple layers to prevent factual errors:

1. **Prompt-level rules** — Strict instructions to never invent information
2. **Profile anchoring** — Projects are explicitly listed in prompts; model can only reference these
3. **Factual project data** — Only real GitHub repositories are included in prompts
4. **Quality review pass** — A second LLM specifically checks for hallucinated content
5. **No fabricated metrics** — Numbers only appear if present in the source CV

---

## Error Handling

- All scrapers have retry logic for network errors
- Groq API calls retry on rate limiting (429) with exponential backoff
- Google Sheets API retries on transient failures (429, 500, 502, 503)
- GitHub Actions uses `continue-on-error: true` — one failure never stops the pipeline
- Each job processes independently — a single failure doesn't block others

---

## Future Improvements

- [ ] A/B testing different prompt strategies per profile
- [ ] Fine-tuned LLM for resume generation
- [ ] Interactive web UI for previewing generated resumes
- [ ] Batch application submission to ATS platforms
- [ ] Resume version comparison and history
- [ ] Custom branding/themes for different companies
- [ ] Real-time scraping with WebSocket job notifications

---

## Modules Reference

| Module | Purpose | Key Functions |
|--------|---------|---------------|
| `main.py` | Orchestrator — ties all modules together | `main()`, `process_job()`, `generate_for_job()` |
| `groq_api.py` | Groq LLM HTTP client | `query_groq()` — handles auth, retries, rate limits |
| `prompts.py` | Profile-specific prompt templates | `detect_profile()`, `build_system_prompt()`, `build_cover_letter_prompt()`, `build_review_prompt()`, `extract_delimited()` |
| `resume_reviewer.py` | Quality review for generated resumes | `review_and_improve()` — grammar, ATS, hallucination check |
| `auto_scorer.py` | AI job scoring | `score_all_unscored()` — scores jobs against CV |
| `auth_sheets.py` | Google Sheets OAuth | `step1()`, `step2()` — PKCE auth flow |
| `naukri_scraper.py` | Naukri job scraper | `fetch_all()`, `save_jobs()`, `merge_into_all_roles()` |
| `indeed_scraper.py` | Indeed job scraper | `fetch_all()`, `save_jobs()`, `merge_into_all_roles()` |
| `linkedin_scraper.py` | LinkedIn job scraper | `fetch_all()`, `save_jobs()`, `merge_into_all_roles()` |

---

## License

MIT
