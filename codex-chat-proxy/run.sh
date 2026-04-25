#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export CODEX_PROXY_API_KEY="${CODEX_PROXY_API_KEY:-codex-proxy-local-key}"
export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-39121}"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "$HOME/miniforge3/bin/python3" ]]; then
    PYTHON_BIN="$HOME/miniforge3/bin/python3"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi
exec "$PYTHON_BIN" app.py
