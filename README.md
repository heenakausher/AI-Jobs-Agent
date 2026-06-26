# AI Jobs Agent

AI-powered job application assistant that scores jobs, generates tailored CVs and cover letters, and tracks applications in Google Sheets.

## Features

- Scores jobs against candidate profile
- Filters high-match opportunities
- Generates tailored CVs (DOCX/PDF)
- Generates personalized cover letters using Groq
- Logs applications to Google Sheets
- Prevents duplicate processing using cached progress

## Project Structure

```
AI-Jobs-Agent/
├── main.py
├── groq_api.py
├── auth_sheets.py
├── all_roles_hyderabad.json
├── requirements.txt
├── outputs/
└── README.md
```

## Requirements

- Python 3.10+
- Groq API Key
- Google Sheets OAuth credentials

Install dependencies:

```bash
pip install -r requirements.txt
```

## Environment Variables

Create a `.env` file:

```env
GROQ_API_KEY=your_groq_api_key
```

## Google Sheets Setup

Generate OAuth token:

```bash
python3 auth_sheets.py step1
```

Authorize access and copy the code.

```bash
python3 auth_sheets.py step2 <authorization_code>
```

This creates `token.json` for future use.

## Run

```bash
python3 main.py
```

Generated CVs and cover letters are saved in:

```text
outputs/
```

## Security

The following files are ignored:

```text
.env
token.json
auth_state.json
client_secret.json
outputs/
score_cache.json
generation_progress.json
```

## Current Focus Areas

- Data Analyst
- Business Intelligence
- Finance
- SAP FICO
- Agentic AI
- AI Engineering
- Machine Learning

## Future Enhancements

- LinkedIn-Naukri-Indeed job ingestion
- Automated applications
- Email integration
- GitHub Actions scheduling
- Cloud deployment

## Author

Kausher