#!/bin/zsh
set -e

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  cp .env.example .env
  open -e .env
  echo "Created .env and opened it in TextEdit."
  echo "Add your Databento API key, save the file, then double-click start.command again."
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

uv sync --extra dev

dashboard_port="${DASHBOARD_PORT:-8765}"
(sleep 1; open "http://127.0.0.1:${dashboard_port}") &
exec uv run uvicorn halfreversal.app:app --host 127.0.0.1 --port "$dashboard_port"
