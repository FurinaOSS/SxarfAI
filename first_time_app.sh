#!/usr/bin/env bash
# First-launch setup for Sxarf AI on Apple Silicon macOS.
#
# Usage: first_time_app.sh [SUPPORT_DIR]
#   main.js passes SUPPORT_DIR as the first argument so the venv, marker and
#   logs always live exactly where main.js expects them. When run by hand with
#   no argument it falls back to ~/Library/Application Support/Sxarf AI.
set -Eeuo pipefail

APP_NAME="Sxarf AI"
RESOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LEGACY_DIR="${HOME}/Library/Application Support/${APP_NAME}"

SUPPORT_DIR="${1:-${SXARF_SUPPORT_DIR:-$LEGACY_DIR}}"
VENV_DIR="${SUPPORT_DIR}/venv"
MARKER="${SUPPORT_DIR}/.first-launch-setup-complete"
LOG_DIR="${SUPPORT_DIR}/Logs"
LOG_FILE="${LOG_DIR}/first-time-setup.log"

# GUI-launched apps get a minimal PATH; make sure Homebrew Pythons are visible.
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"

# Keep Hugging Face downloads inside the support dir (matches main.js).
export HF_HOME="${HF_HOME:-${SUPPORT_DIR}/huggingface}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/hub}"

mkdir -p "$SUPPORT_DIR" "$LOG_DIR" "$HF_HOME"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "========================================"
echo "       ${APP_NAME} first-time setup"
echo "========================================"
echo "Support dir: $SUPPORT_DIR"

# ---------------------------------------------------------------
# Platform checks
# ---------------------------------------------------------------
if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "ERROR: This installer is for macOS only." >&2
    exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
    echo "ERROR: ${APP_NAME}'s MLX runtime requires an Apple Silicon Mac." >&2
    exit 1
fi

# ---------------------------------------------------------------
# Skip if already complete
# ---------------------------------------------------------------
if [[ -f "$MARKER" && -x "$VENV_DIR/bin/python" ]]; then
    if "$VENV_DIR/bin/python" -c 'import importlib.util, sys; sys.exit(importlib.util.find_spec("mlx_whisper") is None)' >/dev/null 2>&1; then
        echo "${APP_NAME} is already set up."
        echo "Python environment: $VENV_DIR"
        exit 0
    fi

    echo "Adding the local speech transcription dependency..."
    "$VENV_DIR/bin/pip" install 'mlx-whisper>=0.4.3'
    exit 0
fi

# ---------------------------------------------------------------
# Find a suitable Python (3.10+)
# ---------------------------------------------------------------
find_python() {
    local candidate version major minor
    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            version="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
            [[ -z "$version" ]] && continue
            major="${version%%.*}"
            minor="${version#*.}"
            if (( major == 3 && minor >= 10 )); then
                command -v "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

if ! BASE_PYTHON="$(find_python)"; then
    echo "ERROR: Python 3.10 or newer was not found." >&2
    echo "Install it (for example: brew install python@3.12), then reopen ${APP_NAME}." >&2
    exit 1
fi

echo "Using Python: $BASE_PYTHON ($("$BASE_PYTHON" --version 2>&1))"

# ---------------------------------------------------------------
# requirements.txt must sit beside this script
# ---------------------------------------------------------------
REQUIREMENTS_FILE="${RESOURCE_DIR}/requirements.txt"

if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
    echo "ERROR: requirements.txt was not found:" >&2
    echo "$REQUIREMENTS_FILE" >&2
    exit 1
fi

# ---------------------------------------------------------------
# Reuse an existing model cache from the legacy location, if any.
# (Virtual environments are not relocatable, so only models are reused.)
# ---------------------------------------------------------------
if [[ "$SUPPORT_DIR" != "$LEGACY_DIR" && -d "$LEGACY_DIR/huggingface/hub" && ! -d "$HF_HOME/hub" ]]; then
    echo
    echo "Found an existing model cache. Reusing it to avoid re-downloading..."
    mkdir -p "$HF_HOME"
    cp -R "$LEGACY_DIR/huggingface/hub" "$HF_HOME/hub" || echo "Could not copy cache; models will be downloaded again."
fi

# ---------------------------------------------------------------
# [1/4] Virtual environment
# ---------------------------------------------------------------
echo
echo "[1/4] Creating Python environment..."

if [[ -d "$VENV_DIR" ]]; then
    rm -rf "$VENV_DIR"
fi

"$BASE_PYTHON" -m venv "$VENV_DIR"

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ---------------------------------------------------------------
# [2/4] Dependencies
# ---------------------------------------------------------------
echo
echo "[2/4] Installing Python dependencies..."

"$PIP" install --upgrade pip
"$PIP" install -r "$REQUIREMENTS_FILE"

"$PYTHON" - <<'PY'
import importlib.util

required = ["mlx_lm", "mlx_whisper", "fastapi", "uvicorn"]
optional = ["mlx_vlm"]

missing = [n for n in required if importlib.util.find_spec(n) is None]
if missing:
    raise SystemExit("Missing required Python packages: " + ", ".join(missing))

for name in optional:
    if importlib.util.find_spec(name) is None:
        print(f"WARNING: optional package '{name}' is not installed.")

print("Required backend packages verified.")
PY

# ---------------------------------------------------------------
# [3/4] Models
# ---------------------------------------------------------------
echo
echo "[3/4] Downloading ${APP_NAME} models..."
echo "This can take a while and requires an internet connection."

hf_cli() {
    if [[ -x "$VENV_DIR/bin/hf" ]]; then
        echo "$VENV_DIR/bin/hf"
    elif [[ -x "$VENV_DIR/bin/huggingface-cli" ]]; then
        echo "$VENV_DIR/bin/huggingface-cli"
    else
        echo "Hugging Face CLI not found. Installing huggingface_hub..." >&2
        "$PIP" install --upgrade huggingface_hub >&2
        if [[ -x "$VENV_DIR/bin/hf" ]]; then
            echo "$VENV_DIR/bin/hf"
        else
            echo "$VENV_DIR/bin/huggingface-cli"
        fi
    fi
}

HF_BIN="$(hf_cli)"

download_model() {
    local repo="$1"
    local attempt

    echo
    echo "Downloading: ${repo}"

    for attempt in 1 2 3; do
        if "$HF_BIN" download "$repo"; then
            return 0
        fi
        echo "Download failed (attempt ${attempt}/3)." >&2
        sleep $(( attempt * 3 ))
    done

    echo "ERROR: Could not download ${repo} after 3 attempts." >&2
    return 1
}

download_model "mlx-community/Qwen3-4B-4bit"
download_model "mlx-community/SmolLM2-360M-Instruct-6bit"
download_model "mlx-community/Qwen3-Reranker-0.6B-mxfp8"
download_model "mlx-community/Qwen3-Embedding-0.6B-8bit"
download_model "mlx-community/whisper-base-mlx"

# ---------------------------------------------------------------
# [4/4] Finalize
# ---------------------------------------------------------------
echo
echo "[4/4] Finalizing setup..."

# Only mark complete after every step has succeeded.
touch "$MARKER"

echo
echo "========================================"
echo "       Setup completed successfully!"
echo "========================================"
echo "Python:      $PYTHON"
echo "Environment: $VENV_DIR"
echo "Models:      $HF_HOME"
echo "Log:         $LOG_FILE"
echo
echo "${APP_NAME} is ready to start its local backend."