"""Resume quality review pass using Groq LLM.

After generating a tailored resume, this module performs an additional review
to verify grammar, professional tone, ATS keyword coverage, hallucinations,
duplicate content, and weak bullet points. It then outputs an improved version.
"""

import logging
from groq_api import query_groq
from prompts import build_review_prompt, extract_delimited

log = logging.getLogger("agent")

REVIEW_MODEL = "llama-3.3-70b-versatile"


def review_and_improve(cv_text: str, job_title: str, job_description: str, max_retries: int = 2) -> str:
    """Review a tailored resume and return an improved version.

    Args:
        cv_text: The generated tailored resume text to review.
        job_title: The target job title.
        job_description: The job description for ATS keyword validation.
        max_retries: Maximum number of API retries.

    Returns:
        The improved resume text, or the original if review fails.
    """
    system_prompt = build_review_prompt()
    user_prompt = (
        f"TARGET JOB TITLE: {job_title}\n\n"
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        f"RESUME TO REVIEW:\n{cv_text}\n\n"
        f"Review the above resume thoroughly and output the improved version."
    )

    for attempt in range(1, max_retries + 1):
        try:
            response = query_groq(system_prompt, user_prompt, model=REVIEW_MODEL)

            improved = extract_delimited(response, "IMPROVED_CV")
            if not improved:
                log.warning("  Review pass: no IMPROVED_CV delimiter found, using original")
                return cv_text

            review_section = extract_delimited(response, "REVIEW")
            if review_section:
                log.info("  Review findings: %s", review_section[:200])

            log.info("  Resume quality review complete — improvements applied")
            return improved

        except Exception as e:
            log.warning("  Review pass attempt %s/%s failed: %s", attempt, max_retries, e)
            if attempt < max_retries:
                import time
                time.sleep(2)

    log.warning("  Review pass failed after %s attempts, using original", max_retries)
    return cv_text
