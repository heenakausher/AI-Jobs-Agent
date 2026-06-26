import logging
import os
import json
import time
import re
import urllib.request
import urllib.error

log = logging.getLogger("agent")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


def _parse_retry_after(body: str) -> float:
    m = re.search(r'Please try again in (\d+(?:\.\d+)?)s', body)
    return float(m.group(1)) + 0.5 if m else 5.0


def query_groq(system_prompt: str, user_prompt: str, model: str = "llama-3.3-70b-versatile", max_retries: int = 3) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3
    }).encode("utf-8")

    last_error = None
    for attempt in range(1 + max_retries):
        req = urllib.request.Request(
            GROQ_API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            if e.code == 429 and attempt < max_retries:
                wait = _parse_retry_after(body)
                log.warning("  Rate limited, waiting %.1fs (attempt %s/%s)...", wait, attempt + 1, max_retries)
                time.sleep(wait)
                last_error = None
                continue
            raise RuntimeError(f"Groq API error {e.code}: {body}")
        except Exception as e:
            raise RuntimeError(f"Request failed: {e}")

    raise RuntimeError(f"Request failed after {max_retries} retries: {last_error}")
