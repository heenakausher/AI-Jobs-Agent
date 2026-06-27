"""Fetch real GitHub repository metadata for a user."""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

log = logging.getLogger("agent")

GITHUB_API_BASE = "https://api.github.com"


def fetch_repos(username: str, max_retries: int = 3) -> List[Dict[str, Any]]:
    """Fetch public repositories for a GitHub user.

    Returns list of dicts with: name, description, languages, stars, topics, readme.
    """
    url = f"{GITHUB_API_BASE}/users/{username}/repos?per_page=50&sort=updated&type=public"
    headers = {
        "User-Agent": "AI-Jobs-Agent/1.0",
        "Accept": "application/vnd.github.v3+json",
    }

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read().decode("utf-8"))
            repos = []
            for repo in data:
                if repo.get("fork", False):
                    continue
                name = repo.get("name", "")
                if not name:
                    continue
                repos.append({
                    "name": name,
                    "description": repo.get("description") or "",
                    "url": repo["html_url"],
                    "stars": repo.get("stargazers_count", 0),
                    "language": repo.get("language") or "",
                    "topics": repo.get("topics", []),
                    "updated_at": repo.get("updated_at", ""),
                })
            repos = _enrich_with_languages_and_readme(repos, username, headers)
            log.info("Fetched %s real repositories for %s", len(repos), username)
            return repos
        except urllib.error.HTTPError as e:
            if e.code == 403 and attempt < max_retries:
                log.warning("GitHub API rate limited, retrying in 60s...")
                time.sleep(60)
                continue
            log.warning("GitHub API error: %s", e)
            return []
        except Exception as e:
            log.warning("Failed to fetch GitHub repos: %s", e)
            if attempt < max_retries:
                time.sleep(5)
                continue
            return []
    return []


def _enrich_with_languages_and_readme(
    repos: List[Dict[str, Any]], username: str, headers: dict
) -> List[Dict[str, Any]]:
    """Fetch languages and README preview for each repo."""
    for repo in repos:
        try:
            lang_url = f"{GITHUB_API_BASE}/repos/{username}/{repo['name']}/languages"
            req = urllib.request.Request(lang_url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=15)
            langs = json.loads(resp.read().decode("utf-8"))
            repo["languages"] = list(langs.keys()) if langs else []
        except Exception:
            repo["languages"] = []

        try:
            readme_url = f"{GITHUB_API_BASE}/repos/{username}/{repo['name']}/readme"
            req = urllib.request.Request(readme_url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=15)
            readme_data = json.loads(resp.read().decode("utf-8"))
            import base64
            content = readme_data.get("content", "")
            if content:
                decoded = base64.b64decode(content).decode("utf-8", errors="replace")
                repo["readme_preview"] = decoded[:500]
            else:
                repo["readme_preview"] = ""
        except Exception:
            repo["readme_preview"] = ""

        time.sleep(0.5)
    return repos


def get_github_projects_data(username: str) -> List[Dict[str, str]]:
    """Get projects formatted for resume generation from real GitHub repos."""
    repos = fetch_repos(username)
    projects = []
    for repo in repos:
        tech = repo.get("language", "") or ""
        if repo.get("languages"):
            tech = ", ".join(repo["languages"][:5])
        desc = repo.get("description") or repo.get("readme_preview", "")[:200] or "No description available"
        projects.append({
            "title": repo["name"],
            "description": desc,
            "technologies": tech or "Various",
            "url": repo["url"],
        })
    return projects
