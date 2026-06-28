"""Profile detection, resume prompts, and helpers with dynamic Groq classification."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from groq_api import query_groq

log = logging.getLogger("agent")

PROFILES = {
    "data analyst": {
        "keywords": ["sql", "power bi", "tableau", "excel", "python", "pandas", "numpy",
                     "dashboard", "visualization", "analytics", "kpi", "reporting"],
        "summary_focus": "data analytics, dashboarding, business intelligence",
        "skill_order": ["Data Analytics", "Visualization & Reporting", "AI / ML & GenAI", "Other Skills"],
    },
    "business intelligence analyst": {
        "keywords": ["power bi", "tableau", "sql", "dashboard", "reporting", "visualization",
                     "etl", "data modeling", "kpi", "business intelligence", "analytics"],
        "summary_focus": "business intelligence, dashboard development, data-driven decision making",
        "skill_order": ["Visualization & Reporting", "Data Analytics", "AI / ML & GenAI", "Other Skills"],
    },
    "financial analyst": {
        "keywords": ["financial analysis", "fp&a", "budgeting", "forecasting", "excel",
                     "financial statements", "variance analysis", "profitability", "cash flow",
                     "ms excel", "ms-office", "tally", "day-to-day accounting", "data entry",
                     "financial record maintenance", "billing", "invoicing", "expense tracking"],
        "summary_focus": "financial analysis, FP&A, budgeting, forecasting",
        "skill_order": ["Finance & Accounting", "Data Analytics", "Visualization & Reporting", "Other Skills"],
    },
    "ai engineer": {
        "keywords": ["llm", "rag", "langchain", "crewai", "vector database", "chroma",
                     "huggingface", "python", "groq", "agentic ai", "prompt engineering"],
        "summary_focus": "AI engineering, LLMs, RAG systems, agentic AI",
        "skill_order": ["AI / ML & GenAI", "Programming", "Data Analytics", "Other Skills"],
    },
    "machine learning engineer": {
        "keywords": ["machine learning", "python", "pandas", "numpy", "scikit-learn",
                     "deep learning", "transformers", "huggingface", "mlops"],
        "summary_focus": "machine learning, predictive modeling, ML pipelines",
        "skill_order": ["AI / ML & GenAI", "Programming", "Data Analytics", "Other Skills"],
    },
    "genai": {
        "keywords": ["generative ai", "llm", "rag", "langchain", "prompt engineering",
                     "gpt", "llama", "groq", "vector database", "chroma"],
        "summary_focus": "generative AI, LLMs, RAG, prompt engineering",
        "skill_order": ["AI / ML & GenAI", "Programming", "Data Analytics", "Other Skills"],
    },
    "llm": {
        "keywords": ["llm", "large language models", "rag", "langchain", "prompt engineering",
                     "fine-tuning", "vector database", "chroma", "huggingface", "groq"],
        "summary_focus": "large language models, RAG, LLM application development",
        "skill_order": ["AI / ML & GenAI", "Programming", "Data Analytics", "Other Skills"],
    },
    "sap fico": {
        "keywords": ["sap", "sap fico", "sap s4 hana", "sap sac", "financial accounting",
                     "controlling", "finance", "accounting"],
        "summary_focus": "SAP FICO, SAP S4 HANA, financial systems",
        "skill_order": ["SAP & ERP", "Finance & Accounting", "Data Analytics", "Other Skills"],
    },
    "data science": {
        "keywords": ["machine learning", "deep learning", "statistics", "python", "r",
                     "predictive modeling", "classification", "regression", "nlp"],
        "summary_focus": "data science, statistical modeling, predictive analytics",
        "skill_order": ["AI / ML & GenAI", "Programming", "Data Analytics", "Other Skills"],
    },
    "power bi": {
        "keywords": ["power bi", "dax", "power query", "power bi service", "dashboard",
                     "reporting", "visualization", "data modeling"],
        "summary_focus": "Power BI development, dashboarding, data visualization",
        "skill_order": ["Visualization & Reporting", "Data Analytics", "AI / ML & GenAI", "Other Skills"],
    },
    "fp&a": {
        "keywords": ["fp&a", "financial planning", "budgeting", "forecasting", "variance analysis",
                     "financial modeling", "excel", "planning", "ms excel", "ms-office", "tally",
                     "day-to-day accounting", "data entry", "financial record maintenance",
                     "billing", "invoicing", "expense tracking"],
        "summary_focus": "financial planning & analysis, FP&A, budgeting, forecasting",
        "skill_order": ["Finance & Accounting", "Data Analytics", "Visualization & Reporting", "Other Skills"],
    },
    "data engineering": {
        "keywords": ["etl", "data pipeline", "data warehouse", "sql", "python", "spark",
                     "airflow", "big data", "data integration"],
        "summary_focus": "data engineering, ETL pipelines, data warehousing",
        "skill_order": ["Programming", "Data Analytics", "AI / ML & GenAI", "Other Skills"],
    },
    "agentic ai": {
        "keywords": ["crewai", "langgraph", "multi-agent", "agent orchestration", "llm",
                     "tool use", "autonomous systems", "python", "groq"],
        "summary_focus": "agentic AI, multi-agent systems, LLM orchestration",
        "skill_order": ["AI / ML & GenAI", "Agentic AI", "Programming", "Other Skills"],
    },
}

PROJECTS_DATA = [
    {
        "title": "Agentic AI — Multi-Agent Newsletter Generator",
        "description": "Built an autonomous multi-agent system using CrewAI where 3 AI agents (Researcher, Writer, Proofreader) collaborate to research, write, and proofread newsletter articles end-to-end.",
        "impact": "Demonstrates production-ready agent orchestration with live web search integration and automated content generation pipeline.",
        "technologies": "Python, CrewAI, Groq LLM, LiteLLM, SerperDev API",
        "url": "https://github.com/heenakausher/Agentic-AI",
    },
    {
        "title": "AI Chatbot RAG — Retrieval-Augmented Generation Chatbot",
        "description": "Implemented a 3-phase RAG chatbot with Streamlit frontend: basic chatbot, LLM-powered conversational agent, and PDF-based Q&A system using retrieval-augmented generation.",
        "impact": "Enables users to upload PDFs and ask natural language questions over document content using semantic search and LLM generation.",
        "technologies": "Python, LangChain, Streamlit, Groq LLM, HuggingFace Embeddings, Chroma DB",
        "url": "https://github.com/heenakausher/ai-chatbot-rag",
    },
    {
        "title": "AI Jobs Agent — Automated Job Application Pipeline",
        "description": "Built a fully automated job scraping, AI scoring, and tailored resume/cover letter generation system with Google Sheets integration and GitHub Actions CI/CD.",
        "impact": "Automates the entire job application workflow from discovery to tailored application materials at scale.",
        "technologies": "Python, Groq LLM, CrewAI, GitHub Actions, Google Sheets API, DOCX/PDF Generation",
        "url": "https://github.com/heenakausher/AI-Jobs-Agent",
    },
    {
        "title": "GitHub Actions CI/CD Pipeline",
        "description": "Implemented automated CI/CD workflows for Python applications including testing, linting, and deployment using GitHub Actions.",
        "impact": "Established automated quality assurance and deployment pipeline following DevOps best practices.",
        "technologies": "GitHub Actions, YAML, Python, CI/CD",
        "url": "https://github.com/heenakausher/apptestgithubaction",
    },
]


def detect_profile(job_title: str, job_description: str, category: str = "") -> str:
    """Detect the best-matching profile for a job using title + keyword matching."""
    title_lower = job_title.lower()
    text = f"{title_lower} {category} {job_description}".lower()

    title_variants = {
        "genai": [r'\bgenai\b', r'\bgenerative\s+ai\b'],
        "llm": [r'\bllm\b', r'\blarge\s+language\s+model'],
        "sap fico": [r'\bsap\s+fico\b'],
        "agentic ai": [r'\bagentic\s+ai\b'],
        "ai engineer": [r'\bai\s+engineer\b'],
        "machine learning engineer": [r'\bmachine\s+learning\b', r'\bml\s+engineer\b'],
        "business intelligence analyst": [r'\bbusiness\s+intelligence\b', r'\bbi\s+analyst\b'],
        "financial analyst": [r'\bfinancial\s+analyst\b'],
        "data analyst": [r'\bdata\s+analyst\b'],
        "data science": [r'\bdata\s+scientist\b'],
        "data engineering": [r'\bdata\s+engineer\b'],
        "power bi": [r'\bpower\s+bi\b'],
        "fp&a": [r'\bfp&a\b', r'\bfinancial\s+planning\b'],
    }

    detected = []
    for profile, patterns in title_variants.items():
        for pat in patterns:
            if re.search(pat, title_lower):
                detected.append(profile)
                break

    if detected:
        order = [
            "agentic ai", "genai", "llm", "ai engineer",
            "machine learning engineer", "data science",
            "sap fico", "financial analyst", "fp&a",
            "business intelligence analyst", "power bi",
            "data engineering", "data analyst",
        ]
        for p in order:
            if p in detected:
                return p
        return detected[0]

    scores = {}
    for profile, config in PROFILES.items():
        score = sum(3 if kw in title_lower else (2 if kw in text else 0) for kw in config["keywords"])
        scores[profile] = score

    best_score = max(scores.values()) if scores else 0
    if best_score == 0:
        return "data analyst"

    candidates = [p for p, s in scores.items() if s == best_score]
    preference_order = [
        "agentic ai", "ai engineer", "machine learning engineer",
        "genai", "llm", "data science",
        "sap fico", "fp&a", "financial analyst",
        "business intelligence analyst", "power bi",
        "data engineering", "data analyst",
    ]
    for preferred in preference_order:
        if preferred in candidates:
            return preferred
    return candidates[0]


def _get_relevant_projects(profile: str, max_projects: int = 4) -> list:
    """Get relevant projects based on profile."""
    ai_profiles = ("ai engineer", "agentic ai", "machine learning engineer", "genai", "llm", "data science")
    if profile in ai_profiles:
        return PROJECTS_DATA[:max_projects]
    return PROJECTS_DATA[:max_projects]


def build_system_prompt(profile: str, cv_text: str) -> str:
    """Build profile-specific system prompt with hallucination prevention."""
    profile_config = PROFILES.get(profile, PROFILES["data analyst"])
    projects = _get_relevant_projects(profile)
    projects_text = _format_projects_for_prompt(projects)

    return f"""You are an expert ATS optimization specialist, professional resume writer, and career coach.

PROFILE FOCUS: {profile_config['summary_focus']}

HALLUCINATION PREVENTION — ABSOLUTE RULES:
1. NEVER invent companies, experience, projects, skills, GitHub repos, metrics, certifications, awards, or dates.
2. ONLY use information from the candidate profile below (enhanced_cv.txt).
3. ONLY include GitHub projects listed in this prompt. NEVER invent repositories.
4. NEVER fabricate numbers, percentages, or metrics.
5. If information is unavailable, omit it. Do NOT guess.
6. Keep all dates, company names, percentages exactly as in the original.
7. Mark any uncertain information as "UNKNOWN".
8. Every fact must be directly traceable to the candidate profile below.

ATS OPTIMIZATION:
- Maximize keyword matching without keyword stuffing
- Use strong action verbs: Developed, Automated, Designed, Built, Optimized, Reduced, Improved, Led
- Use STAR/CAR format for experience bullets
- Organize skills into categories from the candidate profile
- Maximum 2 pages
- Standard section headings: PROFESSIONAL SUMMARY, TECHNICAL SKILLS, WORK EXPERIENCE, GITHUB PROJECTS, EDUCATION, CERTIFICATIONS
- CRITICAL: Output ONLY the resume sections. Do NOT add any preamble, explanation, or first-person notes like "I've added relevant keywords..." — just output the resume content directly.

Use these exact delimiters:

===TAILORED_CV===
Heena Kausher
kausher92@gmail.com | 7898680077 | www.github.com/heenakausher
www.linkedin.com/in/heena-kausher-90418a118 | www.mygreatlearning.com/eportfolio/heena-kausher

PROFESSIONAL SUMMARY
<3-5 line professional summary tailored to target role, ATS-optimized>

TECHNICAL SKILLS
<Organized into categories based on profile focus. Example:>
<Category Name>:
- Skill 1
- Skill 2

WORK EXPERIENCE
<Company Name> — <Date Range>
<Title>
- <Action verb bullet point>
- <Quantified achievement>

GITHUB PROJECTS
{projects_text}

EDUCATION
- MBA - Banking & Finance, NMIMS CDOE | 67.33%
- M.Com - Pt. Ravishankar Shukla University | 46.50%
- B.Com - Pt. Ravishankar Shukla University | 60.44%

CERTIFICATIONS
- PGP in Data Science & Analytics - Great Lakes Executive Learning | GPA: 3.9
- Chartered Accountancy - IPCC (Group-1) | May 2012 | 52.75%
- Chartered Accountancy - CPT | Dec 2010 | 55.00%

===COVER_LETTER===
<Professional cover letter, 300-450 words, personalized to company and role>

===INTERVIEW_PREP===
<Comma-separated list of technical and behavioural topics>

===ACCEPTANCE_CHANCE===
<Number 0-100 representing estimated probability of acceptance>

CANDIDATE'S ORIGINAL PROFILE (use ONLY this information):
{cv_text}"""


def _format_projects_for_prompt(projects: list) -> str:
    lines = []
    for i, proj in enumerate(projects, 1):
        lines.append(f"Project {i}: {proj['title']}")
        lines.append(f"Technologies: {proj['technologies']}")
        lines.append(f"- {proj['description']}")
        lines.append(f"- {proj['impact']}")
        lines.append(f"GitHub: {proj['url']}")
    return "\n".join(lines)


def build_cover_letter_prompt(profile: str, job: dict, cv_text: str) -> str:
    """Build a focused prompt for just the cover letter."""
    profile_config = PROFILES.get(profile, PROFILES["data analyst"])
    return f"""You are a professional cover letter writer specializing in {profile_config['summary_focus']} roles.

Write a professional, concise cover letter (300-450 words) for the following job.

TARGET JOB:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}

JOB DESCRIPTION:
{job.get('description', 'Not available')}

CANDIDATE PROFILE:
{cv_text}

RULES:
- 300-450 words
- Personalized to the specific company and role
- Only reference real skills and experience from the candidate profile
- NEVER invent qualifications, projects, or experience
- Avoid clichés and generic AI wording
- Professional but conversational tone
- End with a clear call to action"""


def extract_delimited(text: str, label: str) -> str:
    """Extract content between ===LABEL=== and next === delimiter."""
    start = text.find(f"==={label}===")
    if start == -1:
        return ""
    start += len(f"==={label}===")
    remaining = ["TAILORED_CV", "COVER_LETTER", "INTERVIEW_PREP", "ACCEPTANCE_CHANCE", "IMPROVED_CV"]
    end = len(text)
    for other in remaining:
        if other == label:
            continue
        pos = text.find(f"==={other}===", start)
        if pos != -1 and pos < end:
            end = pos
    return text[start:end].strip()


def extract_score(text: str) -> int:
    """Extract numeric score from acceptance chance text."""
    m = re.search(r'\b(\d{1,3})\b', text)
    if m:
        return max(0, min(100, int(m.group(1))))
    try:
        digits = "".join(c for c in text if c.isdigit())
        return max(0, min(100, int(digits)))
    except (ValueError, TypeError):
        return 50


def classify_job_profile(job: dict) -> str:
    """Use Groq to dynamically classify a job into the best-fit profile.

    Returns a detailed profile label like 'Business Intelligence', 'Power BI', etc.
    """
    prompt = f"""Given the job listing below, classify it into the single most specific target profile.

Job Title: {job.get('title', '')}
Job Description: {job.get('description', '')[:500]}

Choose from these profiles (return EXACTLY one label):
- Business Intelligence
- Power BI
- Financial Planning
- Commercial Analytics
- GenAI
- Machine Learning
- Data Science
- Python
- Finance Transformation
- FP&A
- Data Engineering
- Data Analyst
- AI Engineer

Return ONLY the profile label, nothing else."""

    try:
        user_msg = f"Classify this job: {job.get('title', '')}"
        response = query_groq(prompt, user_msg, model="llama-3.1-8b-instant")
        response = response.strip().strip('"').strip("'")
        valid = [
            "Business Intelligence", "Power BI", "Financial Planning",
            "Commercial Analytics", "GenAI", "Machine Learning",
            "Data Science", "Python", "Finance Transformation",
            "FP&A", "Data Engineering", "Data Analyst", "AI Engineer",
        ]
        for v in valid:
            if v.lower() in response.lower():
                return v
        return detect_profile(job.get("title", ""), job.get("description", ""), job.get("category", ""))
    except Exception as e:
        log.debug("Groq classification failed: %s", e)
        return detect_profile(job.get("title", ""), job.get("description", ""), job.get("category", ""))
