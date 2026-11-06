#!/bin/bash
set -euo pipefail

APP_DATA="${SXARF_USER_DATA:-${HOME}/Library/Application Support/Sxarf AI}"
PLAN=""
NAME=""
SHOW=false

usage() {
    cat <<'EOF'
Usage: ./choose-plan.sh [--user-data DIR] [--plan PLAN] [--name NAME] [--show]

Plans: Free, Pro, Max, Unlimited
By default, updates the local profile used by Sxarf AI in:
  ~/Library/Application Support/Sxarf AI/local-account.json

The paid plan names only change the locally displayed plan. They do not
activate paid features or create a subscription.
EOF
}

while (($#)); do
    case "$1" in
        --user-data)
            (($# >= 2)) || { echo "Missing path after --user-data." >&2; exit 2; }
            APP_DATA="$2"
            shift 2
            ;;
        --plan)
            (($# >= 2)) || { echo "Missing plan after --plan." >&2; exit 2; }
            PLAN="$2"
            shift 2
            ;;
        --name)
            (($# >= 2)) || { echo "Missing name after --name." >&2; exit 2; }
            NAME="$2"
            shift 2
            ;;
        --show)
            SHOW=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

PROFILE="${APP_DATA}/local-account.json"

show_profile() {
    python3 - "$PROFILE" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except FileNotFoundError:
    data = {"name": "Local Guest", "plan": "Free"}
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"Could not read profile {path}: {error}")

print(f"Profile: {path}")
print(f"Name: {data.get('name', 'Local Guest')}")
print(f"Plan: {data.get('plan', 'Free')}")
PY
}

if [[ "$SHOW" == true ]]; then
    show_profile
    exit 0
fi

if [[ -z "$PLAN" && -z "$NAME" ]]; then
    echo "Sxarf AI local profile"
    echo "1) Change displayed plan"
    echo "2) Change display name"
    echo "3) Show profile"
    echo "4) Exit"
    read -r -p "Choose an option: " choice

    case "$choice" in
        1)
            echo "1) Free  2) Pro  3) Max  4) Unlimited"
            read -r -p "Choose a plan: " selection
            case "$selection" in
                1) PLAN="Free" ;;
                2) PLAN="Pro" ;;
                3) PLAN="Max" ;;
                4) PLAN="Unlimited" ;;
                *) echo "Invalid plan selection." >&2; exit 2 ;;
            esac
            ;;
        2)
            read -r -p "Enter display name: " NAME
            ;;
        3)
            show_profile
            exit 0
            ;;
        4)
            exit 0
            ;;
        *)
            echo "Invalid option." >&2
            exit 2
            ;;
    esac
fi

if [[ -n "$PLAN" ]] && [[ ! "$PLAN" =~ ^(Free|Pro|Max|Unlimited)$ ]]; then
    echo "Invalid plan '$PLAN'. Choose Free, Pro, Max, or Unlimited." >&2
    exit 2
fi

if [[ -n "$NAME" ]]; then
    trimmed_name="$(printf '%s' "$NAME" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    if [[ -z "$trimmed_name" || ${#trimmed_name} -gt 40 ]]; then
        echo "Display name must contain 1–40 non-whitespace characters." >&2
        exit 2
    fi
    NAME="$trimmed_name"
fi

mkdir -p "$APP_DATA"
PROFILE_PLAN="$PLAN" PROFILE_NAME="$NAME" python3 - "$PROFILE" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"Could not read profile {path}: {error}")

if not isinstance(data, dict):
    raise SystemExit(f"Profile must contain a JSON object: {path}")

plan = os.environ.get("PROFILE_PLAN", "")
name = os.environ.get("PROFILE_NAME", "")
if plan:
    data["plan"] = plan
if name:
    data["name"] = name
data.setdefault("name", "Local Guest")
data.setdefault("plan", "Free")

temporary = None
try:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(data, handle, indent=2)
        handle.write("\n")
    temporary.replace(path)
except OSError as error:
    if temporary:
        temporary.unlink(missing_ok=True)
    raise SystemExit(f"Could not update profile {path}: {error}")

print(f"Updated {path}")
print(f"Name: {data['name']}")
print(f"Displayed plan: {data['plan']}")
print("Restart Sxarf AI or reopen Settings to refresh the display.")
print("Note: selecting a paid plan only changes its local display.")
PY
