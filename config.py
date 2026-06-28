"""Configuration — loads search_config.json then exposes typed settings."""

import json
import os
from typing import Any, Dict, List, Optional

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_DIR = os.path.join(_APP_DIR, "config")


def _load_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Search config ────────────────────────────────────────────────
_search_config: Dict[str, Any] = _load_json(
    os.path.join(_CONFIG_DIR, "search_config.json"),
    {}
)

SEARCH_KEYWORDS: List[str] = _search_config.get("keywords", [
    "Data Analyst", "Business Analyst", "Business Intelligence Analyst",
])
SEARCH_CITIES: List[str] = _search_config.get("cities", [
    "Hyderabad", "Pune", "Bengaluru", "Chennai",
])
SEARCH_MODES: Dict[str, bool] = _search_config.get("search_modes", {
    "remote": True,
    "hybrid": True,
    "work_from_home": True,
    "india_wide": True,
})
MAX_PAGES_PER_SEARCH: int = _search_config.get("max_pages_per_search", 10)
MAX_WORKERS: int = _search_config.get("max_workers", 10)
RATE_LIMIT_MIN: float = float(_search_config.get("rate_limit_min_seconds", 2))
RATE_LIMIT_MAX: float = float(_search_config.get("rate_limit_max_seconds", 7))

WEBSITES: Dict[str, bool] = _search_config.get("websites", {
    "naukri": True, "indeed": True, "linkedin": True,
})

# ── Scoring config ────────────────────────────────────────────────
_scoring_config: Dict[str, Any] = _search_config.get("scoring", {})
MIN_AI_SCORE: int = _scoring_config.get("min_score_threshold", 6)
ROLE_WEIGHT: float = _scoring_config.get("role_match_weight", 0.35)
SKILLS_WEIGHT: float = _scoring_config.get("skills_match_weight", 0.25)
EXP_WEIGHT: float = _scoring_config.get("experience_match_weight", 0.15)
LOC_WEIGHT: float = _scoring_config.get("location_match_weight", 0.10)
RECENCY_WEIGHT: float = _scoring_config.get("recency_weight", 0.05)

# ── Blacklist ────────────────────────────────────────────────────
BLACKLIST: List[str] = _load_json(
    os.path.join(_CONFIG_DIR, "blacklist_companies.json"),
    []
)

# ── Static config (unchanged) ────────────────────────────────────
CITIES = SEARCH_CITIES

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
    "indeed": {
        "Internship": "entry_level",
        "Fresher": "entry_level",
        "0-1 years": "entry_level",
        "1-3 years": "mid_level",
        "Mid level": "mid_level",
        "Experienced": "senior_level",
    },
}

REQUEST_TIMEOUT = 30
DUPLICATE_STOP_THRESHOLD = 0.5

# ── Models ────────────────────────────────────────────────────────
GENERATION_MODEL = "llama-3.1-8b-instant"

# ── File paths ────────────────────────────────────────────────────
OUTPUT_DIR = "outputs"
JOBS_JSON = "processed_jobs.json"
CV_FILE = "enhanced_cv.txt"
SCORE_CACHE = "score_cache.json"
PROGRESS_FILE = "generation_progress.json"
STATS_FILE = "agent_stats.json"
HEALTH_FILE = "scraper_health.json"
AGENT_LOG = "agent.log"
SCRAPE_CHECKPOINT = "scrape_checkpoint.json"

# ── Google Sheets ────────────────────────────────────────────────
CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"
SHEET_ID = "1debuNPIgf0hYPIaUyLy42IARIXaNE46Gxp9hB50Y8H0"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ── Health ────────────────────────────────────────────────────────
HEALTH_CONSECUTIVE_ZERO_THRESHOLD = 3

# ── Derived ────────────────────────────────────────────────────────
import datetime
OUTPUT_DATE_DIR = os.path.join(OUTPUT_DIR, datetime.date.today().strftime("%Y-%m-%d"))
