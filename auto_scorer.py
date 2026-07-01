"""Weighted job scoring with detailed breakdowns."""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from config import (
    SCORE_CACHE, JOBS_JSON, CV_FILE,
    ROLE_WEIGHT, SKILLS_WEIGHT, EXP_WEIGHT, LOC_WEIGHT,
    RECENCY_WEIGHT, MIN_AI_SCORE,
)

log = logging.getLogger("agent")


SKILL_KEYWORDS = {
    "data_analyst": [
        "sql", "python", "pandas", "numpy", "excel", "power bi", "tableau",
        "dashboard", "visualization", "analytics", "kpi", "reporting", "etl",
        "data modeling", "statistics", "hypothesis testing", "a/b testing",
    ],
    "finance_roles": [
        "financial analysis", "fp&a", "budgeting", "forecasting", "excel",
        "financial statements", "variance analysis", "profitability", "cash flow",
        "accounting", "taxation", "sap", "audit", "reconciliation",
    ],
    "agentic_ai": [
        "machine learning", "python", "pandas", "numpy", "scikit-learn",
        "deep learning", "transformers", "huggingface", "mlops", "tensorflow",
        "pytorch", "neural networks", "llm", "rag",
    ],
    "genai_llm": [
        "generative ai", "llm", "rag", "langchain", "prompt engineering",
        "gpt", "llama", "vector database", "chroma", "huggingface",
        "fine-tuning", "embedding", "semantic search",
    ],
    "fresher_ai_ml": [
        "python", "sql", "machine learning", "deep learning", "statistics",
        "data analysis", "pandas", "numpy", "linear algebra",
    ],
}

CV_SKILL_CACHE: List[str] = []


def _load_cv_skills() -> List[str]:
    global CV_SKILL_CACHE
    if CV_SKILL_CACHE:
        return CV_SKILL_CACHE
    if not os.path.exists(CV_FILE):
        return []
    with open(CV_FILE, "r", encoding="utf-8") as f:
        text = f.read().lower()
    extracted = re.findall(r'\b[\w+#.]+(?:\s+[\w+#.]+)*\b', text)
    CV_SKILL_CACHE = [s.strip() for s in extracted if len(s.strip()) > 2]
    return CV_SKILL_CACHE


def _normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', text.lower().strip())


def _score_role_match(job: Dict[str, Any], cv_text: str) -> Tuple[float, str]:
    title = _normalize(job.get("title", ""))
    desc = _normalize(job.get("description", ""))
    combined = title + " " + desc

    cv_lower = cv_text.lower()
    score = 0.0
    details = []

    role_terms = {
        "data analyst": ["data analyst", "business analyst", "bi analyst", "analytics"],
        "data scientist": ["data scientist", "ml engineer", "machine learning"],
        "ai engineer": ["ai engineer", "artificial intelligence", "llm", "genai", "rag"],
        "financial analyst": ["financial analyst", "fp&a", "finance analyst"],
        "developer": ["developer", "engineer", "software", "programmer"],
    }

    for role, terms in role_terms.items():
        if any(t in combined for t in terms):
            if role in cv_lower:
                score += 1.0
                details.append(f"Role '{role}' matches CV")
            elif any(t in cv_lower for t in terms):
                score += 0.6
                details.append(f"Role '{role}' partially matches CV")

    score = min(score, 1.0)
    weighted = score * 10 * ROLE_WEIGHT
    return weighted, "; ".join(details) if details else "No strong role match"


def _score_skills_match(job: Dict[str, Any], cv_text: str) -> Tuple[float, str]:
    desc = _normalize(job.get("description", ""))
    cv_lower = cv_text.lower()
    category = job.get("category", "data_analyst")
    relevant_skills = SKILL_KEYWORDS.get(category, SKILL_KEYWORDS["data_analyst"])

    matched = 0
    found_skills = []
    for skill in relevant_skills:
        if skill in desc and skill in cv_lower:
            matched += 1
            found_skills.append(skill)

    max_skills = max(len(relevant_skills), 1)
    score = matched / max_skills
    weighted = score * 10 * SKILLS_WEIGHT
    return weighted, f"Matched {matched}/{len(relevant_skills)} skills: {', '.join(found_skills[:5])}" if found_skills else "No skill match"


def _score_experience_match(job: Dict[str, Any], cv_text: str) -> Tuple[float, str]:
    desc = _normalize(job.get("description", "")).lower()
    title = _normalize(job.get("title", "")).lower()

    # Check for experience requirements
    years_re = re.findall(r'(\d+)\+?\s*(?:years|yrs)', desc)
    if not years_re:
        years_re = re.findall(r'(\d+)\s*-\s*(\d+)\s*(?:years|yrs)', desc)
        if years_re:
            years_req = (int(years_re[0][0]) + int(years_re[0][1])) / 2
        else:
            years_req = 2
    else:
        years_req = int(years_re[0])

    # Extract candidate experience from CV
    cv_years_re = re.findall(r'(\d+)\+?\s*(?:years|yrs)\s+(?:of\s+)?experience', cv_text.lower())
    if not cv_years_re:
        # Estimate from CV content
        cv_years = 3
    else:
        cv_years = int(cv_years_re[0])

    if cv_years >= years_req:
        score = 1.0
    elif cv_years >= years_req * 0.7:
        score = 0.7
    else:
        score = 0.3

    weighted = score * 10 * EXP_WEIGHT
    return weighted, f"CV: ~{cv_years}yrs, Required: ~{years_req}yrs"


def _score_location_match(job: Dict[str, Any]) -> Tuple[float, str]:
    location = _normalize(job.get("location", ""))
    if not location or location in ("remote", "work from home", "all india"):
        return 1.0 * 10 * LOC_WEIGHT, "Remote/WFH — full match"
    if "hybrid" in location:
        return 0.8 * 10 * LOC_WEIGHT, "Hybrid — partial match"
    return 0.5 * 10 * LOC_WEIGHT, f"Onsite ({location})"


def _score_recency(job: Dict[str, Any]) -> Tuple[float, str]:
    date_str = job.get("date", "")
    if not date_str:
        return 0.5 * 10 * RECENCY_WEIGHT, "Unknown date"

    try:
        from datetime import datetime, date
        if isinstance(date_str, str):
            job_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            job_date = date_str
        days_ago = (date.today() - job_date).days
        if days_ago == 0:
            return 1.0 * 10 * RECENCY_WEIGHT, "Posted today"
        elif days_ago <= 1:
            return 0.8 * 10 * RECENCY_WEIGHT, "Posted yesterday"
        elif days_ago <= 3:
            return 0.5 * 10 * RECENCY_WEIGHT, "Posted within 3 days"
        else:
            return 0.2 * 10 * RECENCY_WEIGHT, f"Posted {days_ago} days ago"
    except (ValueError, TypeError):
        return 0.5 * 10 * RECENCY_WEIGHT, "Date parse error"


def score_single_job_to_entry(job: Dict[str, Any], cv_text: str) -> Optional[Dict[str, Any]]:
    """Score a single job and return a cache-ready entry dict, or None on failure."""
    try:
        score, reason, breakdown = score_single_job(job, cv_text)
        return {
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "category": job.get("category", "N/A"),
            "score": score,
            "reason": reason,
            **breakdown,
        }
    except Exception:
        return None


def score_single_job(job: Dict[str, Any], cv_text: str) -> Tuple[int, str, Dict[str, float]]:
    """Score a single job using weighted criteria.

    Returns:
        Tuple of (overall_score_0_10, reason_summary, breakdown_dict)
    """
    role_score, role_detail = _score_role_match(job, cv_text)
    skills_score, skills_detail = _score_skills_match(job, cv_text)
    exp_score, exp_detail = _score_experience_match(job, cv_text)
    loc_score, loc_detail = _score_location_match(job)
    recency_score, recency_detail = _score_recency(job)

    total = role_score + skills_score + exp_score + loc_score + recency_score
    total = max(0, min(10, round(total, 1)))

    breakdown = {
        "role_score": round(role_score, 2),
        "skills_score": round(skills_score, 2),
        "experience_score": round(exp_score, 2),
        "location_score": round(loc_score, 2),
        "recency_score": round(recency_score, 2),
    }

    reason = f"Role: {role_detail} | Skills: {skills_detail} | Exp: {exp_detail}"

    return total, reason, breakdown


def append_single_score(score_entry: Dict[str, Any]) -> None:
    """Append a single scored job entry to score_cache.json."""
    existing = _load_json(SCORE_CACHE)
    existing.append(score_entry)
    _save_json(SCORE_CACHE, existing)


def score_all_unscored() -> int:
    """Score all unscored jobs using weighted criteria."""
    if not os.path.exists(CV_FILE):
        log.error("CV file not found: %s", CV_FILE)
        return 0

    cv_text = open(CV_FILE, "r", encoding="utf-8").read()
    all_jobs = _load_json(JOBS_JSON)
    existing_scores = _load_json(SCORE_CACHE)

    scored_keys = {}
    for s in existing_scores:
        key = (s.get("title", ""), s.get("company", ""))
        scored_keys[key] = True

    unscored = []
    for job in all_jobs:
        key = (job.get("title", ""), job.get("company", ""))
        if key not in scored_keys:
            unscored.append(job)

    if not unscored:
        log.info("No unscored jobs found. All %s jobs already scored.", len(all_jobs))
        return 0

    log.info("Scoring %s unscored jobs with weighted criteria...", len(unscored))
    new_scores = []

    for i, job in enumerate(unscored, 1):
        title = job.get("title", "N/A")
        company = job.get("company", "N/A")
        try:
            score, reason, breakdown = score_single_job(job, cv_text)
            new_scores.append({
                "title": title,
                "company": company,
                "category": job.get("category", "N/A"),
                "score": score,
                "reason": reason,
                **breakdown,
            })
            log.info("  [%s/%s] %s @ %s — Score: %s/10", i, len(unscored), title, company, score)
            log.info("    Breakdown: %s", breakdown)
        except Exception as e:
            log.error("    FAILED: %s — %s", title, e)

    if new_scores:
        existing_scores.extend(new_scores)
        _save_json(SCORE_CACHE, existing_scores)
        log.info("Added %s new scores to %s", len(new_scores), SCORE_CACHE)

    return len(new_scores)


def _load_json(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: str, data: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
