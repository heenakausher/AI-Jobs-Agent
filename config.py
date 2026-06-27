import os
import datetime

CITIES = [
    "Hyderabad",
    "Pune",
    "Bengaluru",
    "Chennai",
    "Remote",
    "All India",
]

EXPERIENCE_LEVELS = [
    "Internship",
    "Fresher",
    "0-1 years",
    "1-3 years",
    "Mid level",
    "Experienced",
]

EXPERIENCE_PARAMS = {
    "naukri": {
        "Internship": "fresher",
        "Fresher": "fresher",
        "0-1 years": "0",
        "1-3 years": "1",
        "Mid level": "3",
        "Experienced": "5",
    },
    "linkedin": {
        "Internship": "1",
        "Fresher": "2",
        "0-1 years": "2",
        "1-3 years": "3",
        "Mid level": "4",
        "Experienced": "5",
    },
}

ROLES_DATA = [
    {"keyword": "Data Analyst", "category": "data_analyst", "synonyms": []},
    {"keyword": "Business Analyst", "category": "data_analyst", "synonyms": []},
    {"keyword": "Business Intelligence", "category": "data_analyst", "synonyms": ["BI", "Analytics", "Reporting", "Dashboard", "MIS"]},
    {"keyword": "Power BI", "category": "data_analyst", "synonyms": []},
    {"keyword": "Data Analytics", "category": "data_analyst", "synonyms": ["Data Analysis"]},
    {"keyword": "Financial Analyst", "category": "finance_roles", "synonyms": []},
    {"keyword": "Finance Executive", "category": "finance_roles", "synonyms": ["Finance Executive"]},
    {"keyword": "Finance Manager", "category": "finance_roles", "synonyms": []},
    {"keyword": "Accounts", "category": "finance_roles", "synonyms": ["Accountant"]},
    {"keyword": "FP&A", "category": "finance_roles", "synonyms": ["Financial Planning", "Financial Planning & Analysis"]},
    {"keyword": "SAP Finance", "category": "finance_roles", "synonyms": ["SAP FICO"]},
    {"keyword": "Machine Learning Engineer", "category": "agentic_ai", "synonyms": ["ML Engineer"]},
    {"keyword": "AI Engineer", "category": "agentic_ai", "synonyms": ["Artificial Intelligence Engineer"]},
    {"keyword": "Generative AI", "category": "genai_llm", "synonyms": []},
    {"keyword": "GenAI", "category": "genai_llm", "synonyms": ["Generative AI", "AI Automation", "Agentic AI"]},
    {"keyword": "LLM", "category": "genai_llm", "synonyms": ["Large Language Model"]},
    {"keyword": "RAG Engineer", "category": "genai_llm", "synonyms": ["RAG"]},
    {"keyword": "Prompt Engineer", "category": "genai_llm", "synonyms": []},
    {"keyword": "Agentic AI", "category": "genai_llm", "synonyms": ["AI Agent"]},
    {"keyword": "Python AI", "category": "genai_llm", "synonyms": []},
    {"keyword": "AI Developer", "category": "genai_llm", "synonyms": []},
    {"keyword": "NLP Engineer", "category": "genai_llm", "synonyms": []},
    {"keyword": "Data Scientist", "category": "agentic_ai", "synonyms": []},
    {"keyword": "Analytics Engineer", "category": "data_analyst", "synonyms": []},
    {"keyword": "AI Intern", "category": "fresher_ai_ml", "synonyms": []},
    {"keyword": "ML Intern", "category": "fresher_ai_ml", "synonyms": []},
    {"keyword": "GenAI Intern", "category": "fresher_ai_ml", "synonyms": []},
]

LEGACY_SEARCHES = [
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

MAX_PAGES = 2
REQUEST_TIMEOUT = 30
CONCURRENT_WORKERS = 10

JOB_AGE_DAYS_FIRST = 7
JOB_AGE_DAYS_SUBSEQUENT = 1
LAST_RUN_FILE = "last_run.json"
SEARCH_CACHE_FILE = "search_cache.json"
DUPLICATE_STOP_THRESHOLD = 0.5

MIN_AI_SCORE = 6
SCORING_MODEL = "llama-3.3-70b-versatile"
GENERATION_MODEL = "llama-3.1-8b-instant"

OUTPUT_DIR = "outputs"
JOBS_JSON = "processed_jobs.json"
CV_FILE = "enhanced_cv.txt"
SCORE_CACHE = "score_cache.json"
PROGRESS_FILE = "generation_progress.json"
STATS_FILE = "agent_stats.json"
HEALTH_FILE = "scraper_health.json"
AGENT_LOG = "agent.log"

CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"
SHEET_ID = "1debuNPIgf0hYPIaUyLy42IARIXaNE46Gxp9hB50Y8H0"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

RATE_LIMIT_NAUKRI = 1.0
RATE_LIMIT_INDEED = 2.0
RATE_LIMIT_LINKEDIN = 2.0

MAX_RETRIES = 3
MAX_RETRIES_SCRAPER = 3

HEALTH_CONSECUTIVE_ZERO_THRESHOLD = 3

OUTPUT_DATE_DIR = os.path.join(OUTPUT_DIR, datetime.date.today().strftime("%Y-%m-%d"))


def get_expanded_searches():
    searches = []
    seen = set()
    for role in ROLES_DATA:
        kw = role["keyword"]
        key = (kw.lower(), role["category"])
        if key not in seen:
            seen.add(key)
            searches.append({"keyword": kw, "category": role["category"]})
        for syn in role.get("synonyms", []):
            key = (syn.lower(), role["category"])
            if key not in seen:
                seen.add(key)
                searches.append({"keyword": syn, "category": role["category"]})
    return searches
