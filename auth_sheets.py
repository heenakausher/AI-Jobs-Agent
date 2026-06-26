"""
Two-step Google Sheets authorization.

Step 1 (run this):  python3 auth_sheets.py step1   → prints URL, saves PKCE state
Step 2 (after auth): python3 auth_sheets.py step2 <code>  → exchanges code for token
"""
import json
import sys
import urllib.request
import urllib.parse
import hashlib
import base64
import secrets
from datetime import datetime, timezone

CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"
AUTH_STATE_FILE = "auth_state.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
REDIRECT_URI = "http://localhost"

with open(CLIENT_SECRET_FILE) as f:
    cfg = json.load(f)
client_id = cfg["installed"]["client_id"]
client_secret = cfg["installed"]["client_secret"]


def step1():
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(16)

    with open(AUTH_STATE_FILE, "w") as f:
        json.dump({"code_verifier": code_verifier, "state": state}, f)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)

    print("=" * 70)
    print("  GOOGLE AUTH — Step 1")
    print("=" * 70)
    print(f"\n  Visit:\n  {auth_url}")
    print(f"\n  Authorize the app. After the redirect fails,")
    print(f"  copy the FULL redirect URL from the address bar.")
    print(f"  Then run:")
    print(f"    python3 auth_sheets.py step2 \"<redirect_url>\"")
    print("=" * 70)


def step2(redirect_url: str):
    with open(AUTH_STATE_FILE) as f:
        auth_state = json.load(f)

    parsed = urllib.parse.urlparse(redirect_url)
    query_params = urllib.parse.parse_qs(parsed.query)
    code = query_params.get("code", [None])[0]

    if not code:
        print("Error: No authorization code found.")
        sys.exit(1)

    token_payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
        "code_verifier": auth_state["code_verifier"],
    }
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode(token_payload).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp = urllib.request.urlopen(req)
    token_data = json.loads(resp.read())

    expiry_dt = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + token_data.get("expires_in", 3600),
        tz=timezone.utc,
    )
    with open(TOKEN_FILE, "w") as f:
        json.dump({
            "token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": SCOPES,
            "expiry": expiry_dt.isoformat(),
        }, f, indent=2)
    print(f"Token saved to {TOKEN_FILE}")

    # Clean up
    import os
    os.remove(AUTH_STATE_FILE)
    print("Ready to run: python3 main.py")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "step1":
        step1()
    elif sys.argv[1] == "step2":
        if len(sys.argv) < 3:
            print("Usage: python3 auth_sheets.py step2 \"<redirect_url>\"")
            sys.exit(1)
        step2(sys.argv[2])
    else:
        print("Usage: python3 auth_sheets.py step1|step2")
        sys.exit(1)
