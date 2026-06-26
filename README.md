# AI Jobs Agent

AI-powered job application assistant that scrapes jobs from Naukri, Indeed, and LinkedIn, scores them using Groq, generates tailored CVs and cover letters, and tracks applications in Google Sheets — fully automated via GitHub Actions.

## Features

- **Scrapes jobs** from Naukri (API), Indeed (HTML), and LinkedIn (public job search)
- **Searches** Hyderabad and Pune for all target roles
- **Target roles**: Data Analyst, Business Analyst, Financial Analyst, Finance, Power BI, SAP FICO, AI Engineer, Agentic AI, Machine Learning, AI Intern, GenAI, LLM, RAG
- **AI scoring** using Groq LLM — evaluates each job against your CV (0-10)
- **Generates tailored CVs** in DOCX + PDF
- **Generates cover letters** personalized for each role
- **Logs applications** to Google Sheets with match %, prep topics, acceptance chance
- **Deduplicates** — never regenerates already-processed jobs
- **Cached** — score_cache.json and generation_progress.json persist across runs
- **Date-stamped outputs** under `outputs/YYYY-MM-DD/`
- **Runs daily** via GitHub Actions (scheduled or manual trigger)

## Project Structure

```
AI-Jobs-Agent/
├── main.py                    # Orchestrator: scraping, scoring, generation, upload
├── groq_api.py                # Groq LLM API client with retry logic
├── auto_scorer.py             # Automated AI job scoring
├── auth_sheets.py             # Google Sheets OAuth flow
├── naukri_scraper.py          # Naukri.com job scraper
├── indeed_scraper.py          # Indeed.com job scraper
├── linkedin_scraper.py        # LinkedIn job scraper
├── reformat_cv.py             # Utility to reformat existing CVs
├── deploy.sh                  # Local deployment script
├── requirements.txt           # Python dependencies
├── processed_jobs.json        # Central job store (all sources merged)
├── score_cache.json           # Cached job scores
├── generation_progress.json   # Tracks generated CVs/letters
├── enhanced_cv.txt            # Your CV text (used for tailoring)
├── .github/workflows/
│   └── daily-agent.yml        # GitHub Actions automation
└── outputs/
    └── YYYY-MM-DD/            # Date-stamped generated files
        └── company_title/
            ├── tailored_cv.docx
            ├── tailored_cv.pdf
            ├── cover_letter.docx
            └── cover_letter.pdf
```

## Requirements

- Python 3.10+
- Groq API Key
- Google Sheets OAuth credentials

### Python Dependencies

```bash
pip install -r requirements.txt
```

## Setup

### 1. Environment Variables

Set these in your environment or `.env` file:

```env
GROQ_API_KEY=gsk_your_groq_api_key
```

### 2. Candidate CV

Place your CV as plain text in `enhanced_cv.txt`. This is used as the source material for tailoring.

### 3. Google Sheets Setup

You need a Google Cloud project with Sheets API enabled:

```bash
# Step 1: Generate auth URL
python3 auth_sheets.py step1

# Step 2: Visit the URL, authorize, paste the redirect URL
python3 auth_sheets.py step2 "<redirect_url>"
```

This creates `token.json` and `client_secret.json`.

### 4. Local Run

```bash
# Fetch new jobs and run the full pipeline
python3 main.py --fetch-naukri --fetch-indeed --fetch-linkedin --auto-score
```

Flags:
- `--fetch-naukri` — scrape Naukri
- `--fetch-indeed` — scrape Indeed
- `--fetch-linkedin` — scrape LinkedIn
- `--only-naukri` / `--only-indeed` / `--only-linkedin` — fetch only, stop
- `--auto-score` — AI-score unscored jobs
- `--location <city>` — override default location

### 5. Deploy Script

```bash
bash deploy.sh --setup    # one-time setup (venv, deps, fonts)
bash deploy.sh --run      # run the agent
```

## GitHub Actions Automation

The workflow runs daily at 03:00 UTC and can also be triggered manually.

### Workflow Steps

1. Checkout repository
2. Setup Python 3.10
3. Install system fonts (PDF generation)
4. Install Python dependencies
5. Restore cached `score_cache.json` and `generation_progress.json`
6. Restore Google OAuth from GitHub Secrets
7. Scrape Naukri jobs (continues on error)
8. Scrape Indeed jobs (continues on error)
9. Scrape LinkedIn jobs (continues on error)
10. Auto-score new jobs with Groq
11. Generate CVs and Cover Letters
12. Upload to Google Sheets
13. Save updated cache
14. Upload generated files as artifacts
15. Commit updated cache files back to repository

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `GROQ_API_KEY` | Your Groq API key (e.g., `gsk_...`) |
| `GOOGLE_CLIENT_SECRET` | Full contents of `client_secret.json` |
| `GOOGLE_TOKEN_JSON` | Full contents of `token.json` |

To set these up:
1. Go to Settings → Secrets and variables → Actions
2. Add each secret by pasting the raw file contents

### How to set up Google Secrets

```bash
# Copy the secret JSON contents to your clipboard
cat client_secret.json | pbcopy   # macOS
cat client_secret.json | xclip    # Linux

# Paste into GOOGLE_CLIENT_SECRET secret on GitHub
# Do the same for token.json into GOOGLE_TOKEN_JSON
```

### Caching

- `score_cache.json` — persists scored jobs between runs. Restored from cache or Git.
- `generation_progress.json` — prevents regenerating CVs/letters. Restored from cache or Git.
- Both are committed back to the repo after each workflow run.

## Job Sources

| Source | Method | Notes |
|--------|--------|-------|
| Naukri | Official API | Uses Naukri job API v3 |
| Indeed | HTML scraping | Parses search results and job descriptions |
| LinkedIn | Public job search | Uses LinkedIn guest API endpoints |

## Locations

Jobs are searched in:
- Hyderabad
- Pune

## Scoring

Two modes:
1. **Manual** — edit `score_cache.json` directly with scores 0-10
2. **Auto-score** (`--auto-score`) — uses Groq to score unscored jobs against your CV

Only jobs with score > 6 are processed for CV/cover letter generation.

## Output

Generated files are stored under `outputs/YYYY-MM-DD/company_title/`:
- `tailored_cv.docx` — Microsoft Word format
- `tailored_cv.pdf` — PDF format
- `cover_letter.docx` — Cover letter in Word format
- `cover_letter.pdf` — Cover letter in PDF format

## Logging

The agent logs all activity to `agent.log`:
- Jobs scraped per source
- Jobs scored (auto or manual)
- Jobs skipped (already processed)
- CVs generated
- Cover letters generated
- Google Sheets uploads
- Failures and errors
- Execution time

## Error Handling

- All scrapers have retry logic for network errors
- Groq API calls retry on rate limiting (429)
- Google Sheets API retries on transient failures
- The GitHub Actions workflow uses `continue-on-error: true` — one failed step never stops the pipeline
- Each job is processed independently — a single failure doesn't block others

## License

MIT
