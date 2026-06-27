"""Resume quality review with ATS scoring, grammar check, and auto-correction."""

import logging
import re
from typing import Optional, Tuple

from groq_api import query_groq
from prompts import extract_delimited

log = logging.getLogger("agent")

REVIEW_MODEL = "llama-3.3-70b-versatile"


def review_and_improve(cv_text: str, job_title: str, job_description: str, max_retries: int = 2) -> str:
    """Review tailored resume and return improved version.

    Checks: ATS score, grammar, keyword coverage, hallucinations, weak bullets.
    Returns improved CV if score is below threshold, otherwise original.
    """
    system_prompt = """You are an expert resume reviewer and ATS optimization specialist.

Review the following resume for:
1. ATS COMPATIBILITY (0-100): Check formatting, keyword density, section headers
2. GRAMMAR & TYPOS: Spelling, punctuation, grammar errors
3. KEYWORD COVERAGE: Are relevant job description keywords present?
4. HALLUCINATIONS: Any fabricated information not in the candidate profile
5. WEAK BULLETS: Bullet points lacking action verbs or measurable impact
6. CONSISTENCY: Formatting, tense, spacing

Output format:

===REVIEW===
ATS Score: <0-100>
Issues Found:
- <issue description>
- <issue description>

===IMPROVED_CV===
<Full improved resume with all issues fixed>

Rules:
- Do NOT change factual information
- Do NOT add fabricated achievements
- Do NOT invent projects or experience
- Only fix identified issues
- Maintain same section structure"""

    user_prompt = (
        f"TARGET JOB TITLE: {job_title}\n\n"
        f"JOB DESCRIPTION:\n{job_description[:2000]}\n\n"
        f"RESUME TO REVIEW:\n{cv_text}\n\n"
        f"Review and improve."
    )

    for attempt in range(1, max_retries + 1):
        try:
            response = query_groq(system_prompt, user_prompt, model=REVIEW_MODEL)

            # Extract ATS score to decide if rewrite needed
            ats_score = _extract_ats_score(response)
            log.info("  Resume ATS score: %s/100", ats_score)

            improved = extract_delimited(response, "IMPROVED_CV")

            if not improved:
                log.warning("  Review pass: no IMPROVED_CV delimiter found, using original")
                return cv_text

            if ats_score is not None and ats_score >= 90:
                log.info("  ATS score >= 90, no rewrite needed")
                return cv_text

            review_section = extract_delimited(response, "REVIEW")
            if review_section:
                log.info("  Review: %s", review_section[:300])

            log.info("  Resume quality improved — ATS score was %s", ats_score)
            return improved

        except Exception as e:
            log.warning("  Review pass attempt %s/%s failed: %s", attempt, max_retries, e)
            if attempt < max_retries:
                import time
                time.sleep(3)

    log.warning("  Review pass failed after %s attempts, using original", max_retries)
    return cv_text


def _extract_ats_score(text: str) -> Optional[int]:
    """Extract ATS score from review output."""
    m = re.search(r'ATS\s*Score\s*:?\s*(\d+)', text, re.IGNORECASE)
    if m:
        return min(100, max(0, int(m.group(1))))
    return None
