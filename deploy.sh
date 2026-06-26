#!/usr/bin/env bash
set -euo pipefail

# ────────────────────────────────────────────────────────────────
# AI Jobs Agent — Deploy / Run Script
# ────────────────────────────────────────────────────────────────
# Usage:  bash deploy.sh
#   or :  bash deploy.sh --setup    # first-time setup
#   or :  bash deploy.sh --run      # run the agent
# ────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Config ──────────────────────────────────────────────────────
PYTHON="${PYTHON:-python3}"
VENV_DIR="${VENV_DIR:-venv}"
LOG_FILE="${LOG_FILE:-agent.log}"
ENV_FILE="${ENV_FILE:-.env}"

# Load .env if present (no overwrite of existing env vars)
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$ENV_FILE"
    set +a
fi

# ── Timestamp helper ─────────────────────────────────────────────
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# ── Commands ─────────────────────────────────────────────────────

cmd_setup() {
    log "=== AI Jobs Agent — Setup ==="

    # System dependencies (Debian/Ubuntu)
    if command -v apt-get &>/dev/null; then
        log "Installing system packages..."
        sudo apt-get update -qq
        sudo apt-get install -y -qq \
            python3 \
            python3-venv \
            python3-pip \
            fonts-dejavu-core \
            2>&1 | tee -a "$LOG_FILE"
    fi

    # Python virtual environment
    if [ ! -d "$VENV_DIR" ]; then
        log "Creating Python virtual environment..."
        "$PYTHON" -m venv "$VENV_DIR"
    fi

    log "Installing Python dependencies..."
    "$VENV_DIR/bin/pip" install --upgrade pip -q
    "$VENV_DIR/bin/pip" install -r requirements.txt -q

    # Check for required files
    local missing=0
    for f in enhanced_cv.txt all_roles_hyderabad.json score_cache.json; do
        if [ ! -f "$f" ]; then
            log "WARNING: Missing $f"
            missing=1
        fi
    done

    # Google OAuth — client secret
    local cs_count
    cs_count=$(ls client_secret.json 2>/dev/null | wc -l)
    if [ "$cs_count" -eq 0 ]; then
        log "WARNING: No client_secret.json found. Google Sheets auth will fail."
        log "  Place your OAuth client secret JSON in this directory."
        missing=1
    fi

    # GROQ_API_KEY check
    if [ -z "${GROQ_API_KEY:-}" ]; then
        log "WARNING: GROQ_API_KEY is not set."
        log "  Set it via:  export GROQ_API_KEY='gsk_...'"
        log "  Or create a .env file (see .env.example)."
        missing=1
    fi

    if [ "$missing" -eq 0 ]; then
        log "Setup complete. Run:  bash deploy.sh --run"
    else
        log "Setup finished with warnings (see above)."
    fi
}

cmd_run() {
    log "=== AI Jobs Agent — Run ==="

    # Ensure venv exists
    if [ ! -d "$VENV_DIR" ]; then
        log "Virtual environment not found. Running setup first..."
        cmd_setup
    fi

    # Activate and run
    # shellcheck disable=SC1091
    . "$VENV_DIR/bin/activate"

    # Run the agent
    "$VENV_DIR/bin/python" main.py 2>&1 | tee -a "$LOG_FILE"

    local exit_code="${PIPESTATUS[0]}"
    if [ "$exit_code" -eq 0 ]; then
        log "Agent finished successfully."
    else
        log "Agent finished with exit code $exit_code."
    fi

    return "$exit_code"
}

cmd_auth() {
    log "=== Google Sheets Auth ==="
    # shellcheck disable=SC1091
    . "$VENV_DIR/bin/activate"

    case "${1:-}" in
        step1|"")
            log "Starting Step 1 — visit the URL below to authorize."
            "$VENV_DIR/bin/python" auth_sheets.py step1
            ;;
        step2)
            if [ -z "${2:-}" ]; then
                echo "Usage: bash deploy.sh --auth step2 <redirect_url>"
                exit 1
            fi
            log "Exchanging auth code for token..."
            "$VENV_DIR/bin/python" auth_sheets.py step2 "$2"
            ;;
        *)
            echo "Unknown auth command: $1"
            echo "Usage: bash deploy.sh --auth [step1|step2 <url>]"
            exit 1
            ;;
    esac
}

# ── Dispatch ─────────────────────────────────────────────────────

case "${1:-}" in
    --setup|setup)
        cmd_setup
        ;;
    --run|run)
        cmd_run
        ;;
    --auth|auth)
        shift
        cmd_auth "$@"
        ;;
    --help|help|-h|"")
        echo "AI Jobs Agent — Deploy Script"
        echo ""
        echo "Usage:"
        echo "  bash deploy.sh --setup       First-time setup (system deps, venv, pip)"
        echo "  bash deploy.sh --run         Run the agent"
        echo "  bash deploy.sh --auth step1  Google OAuth step 1"
        echo "  bash deploy.sh --auth step2  Google OAuth step 2"
        echo "                               <redirect_url>"
        echo "  bash deploy.sh --help        Show this help"
        echo ""
        echo "Environment variables:"
        echo "  GROQ_API_KEY   Groq API key (or put in .env)"
        echo "  PYTHON         Python command (default: python3)"
        echo "  VENV_DIR       Virtual env directory (default: venv)"
        echo "  LOG_FILE       Log file path (default: agent.log)"
        ;;
    *)
        echo "Unknown command: $1"
        echo "Run: bash deploy.sh --help"
        exit 1
        ;;
esac
