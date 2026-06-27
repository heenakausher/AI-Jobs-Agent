"""CSV reports generation."""

import csv
import json
import logging
import os
from typing import Any, Dict, List, Optional

log = logging.getLogger("agent")

REPORTS_DIR = "outputs/reports"


def _ensure_dir() -> None:
    os.makedirs(REPORTS_DIR, exist_ok=True)


def _write_csv(path: str, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    _ensure_dir()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    log.info("  Wrote %s rows to %s", len(rows), path)


def write_jobs_scraped(jobs: List[Dict[str, Any]]) -> str:
    path = os.path.join(REPORTS_DIR, "jobs_scraped.csv")
    fieldnames = ["title", "company", "location", "category", "source", "date", "url", "job_id"]
    rows = []
    for j in jobs:
        rows.append({
            "title": j.get("title", ""),
            "company": j.get("company", ""),
            "location": j.get("location", ""),
            "category": j.get("category", ""),
            "source": j.get("source", ""),
            "date": j.get("date", ""),
            "url": j.get("url", ""),
            "job_id": j.get("job_id", ""),
        })
    _write_csv(path, fieldnames, rows)
    return path


def write_jobs_filtered(jobs: List[Dict[str, Any]]) -> str:
    path = os.path.join(REPORTS_DIR, "jobs_filtered.csv")
    fieldnames = ["title", "company", "location", "source", "rejection_reason"]
    rows = []
    for j in jobs:
        rows.append({
            "title": j.get("title", ""),
            "company": j.get("company", ""),
            "location": j.get("location", ""),
            "source": j.get("source", ""),
            "rejection_reason": j.get("rejection_reason", ""),
        })
    _write_csv(path, fieldnames, rows)
    return path


def write_recommended_jobs(jobs: List[Dict[str, Any]]) -> str:
    path = os.path.join(REPORTS_DIR, "recommended_jobs.csv")
    fieldnames = [
        "title", "company", "location", "category", "score",
        "role_score", "skills_score", "experience_score",
        "location_score", "salary_score", "recency_score",
        "score_reason",
    ]
    _write_csv(path, fieldnames, jobs)
    return path


def write_applied_jobs(jobs: List[Dict[str, Any]]) -> str:
    path = os.path.join(REPORTS_DIR, "applied_jobs.csv")
    fieldnames = [
        "title", "company", "location", "score",
        "profile", "match_pct", "folder",
    ]
    rows = []
    for j in jobs:
        rows.append({
            "title": j.get("title", ""),
            "company": j.get("company", ""),
            "location": j.get("location", ""),
            "score": j.get("score", ""),
            "profile": j.get("profile", ""),
            "match_pct": j.get("match_pct", ""),
            "folder": j.get("folder", ""),
        })
    _write_csv(path, fieldnames, rows)
    return path
