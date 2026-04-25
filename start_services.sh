#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CODEX_PROXY_API_KEY="${CODEX_PROXY_API_KEY:-codex-proxy-local-key}"
GEMINI_PROXY_API_KEY="${GEMINI_PROXY_API_KEY:-gemini-proxy-local-key}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-litellm-local-test-key}"
LITELLM_BIN="${LITELLM_BIN:-$(command -v litellm)}"

restart_session() {
  local name="$1"
  local command="$2"
  if tmux has-session -t "$name" 2>/dev/null; then
    tmux kill-session -t "$name"
  fi
  tmux new -s "$name" -d "$command"
}

restart_session "codex_chat_proxy" \
  "cd \"$ROOT/codex-chat-proxy\" && CODEX_PROXY_API_KEY=\"$CODEX_PROXY_API_KEY\" ./run.sh > /tmp/codex-chat-proxy.log 2>&1"

restart_session "gemini_genai_proxy" \
  "cd \"$ROOT/gemini-genai-proxy\" && GEMINI_PROXY_API_KEY=\"$GEMINI_PROXY_API_KEY\" ./run.sh > /tmp/gemini-genai-proxy.log 2>&1"

restart_session "litellm_two_proxy" \
  "cd \"$ROOT\" && CODEX_PROXY_API_KEY=\"$CODEX_PROXY_API_KEY\" GEMINI_PROXY_API_KEY=\"$GEMINI_PROXY_API_KEY\" LITELLM_MASTER_KEY=\"$LITELLM_MASTER_KEY\" \"$LITELLM_BIN\" --config \"$ROOT/litellm-two-proxy.yaml\" --host 127.0.0.1 --port 4000 > /tmp/litellm-two-proxy.log 2>&1"

cat <<EOF
Started tmux sessions:
  codex_chat_proxy       http://127.0.0.1:39121
  gemini_genai_proxy     http://127.0.0.1:39122
  litellm_two_proxy      http://127.0.0.1:4000

Logs:
  /tmp/codex-chat-proxy.log
  /tmp/gemini-genai-proxy.log
  /tmp/litellm-two-proxy.log
EOF
