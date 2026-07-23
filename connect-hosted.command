#!/bin/zsh
set -e

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  cp .env.example .env
  open -e .env
  echo "Created .env and opened it in TextEdit."
  echo "Add the hosted URL, access key and Databento key, save, then run again."
  read -r "?Press Return to close..."
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Install uv from https://docs.astral.sh/uv/getting-started/installation/ then run again."
  read -r "?Press Return to close..."
  exit 1
fi

set -a
source .env
set +a

if [[ -z "${HOSTED_DASHBOARD_URL:-}" || -z "${BRIDGE_TOKEN:-}" ]]; then
  open -e .env
  echo "HOSTED_DASHBOARD_URL and BRIDGE_TOKEN are required in .env."
  read -r "?Press Return to close..."
  exit 1
fi

uv sync --extra dev
uv run uvicorn halfreversal.app:app --host 127.0.0.1 --port 8765 &
local_service_pid=$!
trap 'kill "$local_service_pid" 2>/dev/null || true' EXIT INT TERM
(sleep 2; open "$HOSTED_DASHBOARD_URL") &
uv run python -m halfreversal.bridge
