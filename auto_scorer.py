import json
import logging
import os
import time
from groq_api import query_groq

log = logging.getLogger("agent")

SCORE_CACHE = "score_cache.json"
ALL_ROLES_FILE = "processed_jobs.json"
CV_FILE = "enhanced_cv.txt"
MODEL = "llama-3.3-70b-versatile"

SCORING_PROMPT = """You are an expert ATS and career coach evaluating how well a candidate's profile matches a job description.

CANDIDATE PROFILE:
{cv}

Evaluate the match between the candidate and this job. Consider:
1. Skills match (technical & domain)
2. Experience relevance (years, industry)
3. Education alignment
4. Overall fit

Return ONLY valid JSON with exactly two fields:
  "score": <integer 0-10>
  "reason": "<one-sentence justification>"

Rules:
- Score 9-10: Exceptional match (most skills + experience directly align)
- Score 7-8: Strong match (key skills align, some gaps)
- Score 5-6: Moderate match (some overlap but significant gaps)
- Score 1-4: Weak match (minimal alignment)
- Score 0: Completely unrelated
- Be honest and critical. Do NOT inflate scores."""


def load_json(path: str):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def score_single_job(job: dict, cv_text: str, max_retries: int = 3) -> tuple:
    user_prompt = f"""TITLE: {job.get('title', 'N/A')}
COMPANY: {job.get('company', 'N/A')}
LOCATION: {job.get('location', 'N/A')}
CATEGORY: {job.get('category', 'N/A')}

DESCRIPTION:
{job.get('description', 'Not available')}"""

    for attempt in range(1, max_retries + 1):
        try:
            response = query_groq(SCORING_PROMPT.format(cv=cv_text), user_prompt, model=MODEL)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1] if "\n" in response else response
                response = response.rsplit("\n", 1)[0] if response.endswith("```") else response
            result = json.loads(response)
            score = int(result.get("score", 0))
            score = max(0, min(10, score))
            reason = result.get("reason", "Auto-scored")
            return score, reason
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            log.warning("  Score parse error (attempt %s/%s): %s", attempt, max_retries, e)
            time.sleep(2)
        except Exception as e:
            log.warning("  Score error (attempt %s/%s): %s", attempt, max_retries, e)
            time.sleep(3)

    return 0, "Auto-score failed"


def score_all_unscored(cv_path: str = CV_FILE, all_roles_path: str = ALL_ROLES_FILE, score_cache_path: str = SCORE_CACHE) -> int:
    cv_text = open(cv_path, "r", encoding="utf-8").read()
    all_jobs = load_json(all_roles_path)
    existing_scores = load_json(score_cache_path)

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

    log.info("Scoring %s unscored jobs with Groq...", len(unscored))
    new_scores = []
    for i, job in enumerate(unscored, 1):
        title = job.get("title", "N/A")
        company = job.get("company", "N/A")
        log.info("  [%s/%s] Scoring: %s @ %s", i, len(unscored), title, company)
        try:
            score, reason = score_single_job(job, cv_text)
            new_scores.append({
                "title": title,
                "company": company,
                "category": job.get("category", "N/A"),
                "score": score,
                "reason": reason,
            })
            log.info("    Score: %s/10 — %s", score, reason)
        except Exception as e:
            log.error("    FAILED: %s", e)
        if i < len(unscored):
            time.sleep(1.5)

    if new_scores:
        existing_scores.extend(new_scores)
        save_json(score_cache_path, existing_scores)
        log.info("Added %s new scores to %s", len(new_scores), score_cache_path)

    return len(new_scores)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("agent")
    added = score_all_unscored()
    log.info("Done. %s new scores added.", added)
