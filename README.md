# Two Proxy Services

This folder contains two standalone local proxy services:

- `codex-chat-proxy`: OpenAI-compatible `/v1/chat/completions` and `/v1/responses`, backed by Codex OAuth.
- `gemini-genai-proxy`: Gemini Developer API compatible `/v1beta`, backed by Gemini CLI OAuth.

LiteLLM reads `litellm-two-proxy.yaml` and exposes both through OpenAI-compatible and Anthropic-compatible endpoints.

## App and Service Manager

The cross-platform manager stores settings in the user config directory, not in `.zshrc`:

- macOS: `~/Library/Application Support/LocalAIProxyStack/config.json`
- Linux: `~/.config/local-ai-proxy-stack/config.json`
- Windows: `%APPDATA%\LocalAIProxyStack\config.json`

Start the services from source:

```sh
cd /Users/yingfanqaq/mycodelibrary/proxy
python3 -m proxy_stack start
```

Open the tray app and settings page:

```sh
cd /Users/yingfanqaq/mycodelibrary/proxy
python3 -m proxy_stack tray --start-services --open-settings
```

Useful manager commands:

```sh
python3 -m proxy_stack status
python3 -m proxy_stack restart
python3 -m proxy_stack env
python3 -m proxy_stack install-autostart
python3 -m proxy_stack uninstall-autostart
```

Default endpoints and keys:

```sh
OPENAI_BASE_URL=http://127.0.0.1:39121/v1
OPENAI_API_KEY=codex-proxy-local-key

GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:39122
GEMINI_API_KEY=gemini-proxy-local-key

ANTHROPIC_BASE_URL=http://127.0.0.1:4000
ANTHROPIC_API_KEY=litellm-local-test-key
```

## Claude Code

Claude Code talks Anthropic Messages API, so point it at LiteLLM, not the lower-level `39121` or `39122` proxy ports. `ANTHROPIC_API_KEY` is the LiteLLM master key.

Codex model aliases exposed to Claude Code:

```sh
ANTHROPIC_BASE_URL=http://127.0.0.1:4000
ANTHROPIC_API_KEY=litellm-local-test-key
ANTHROPIC_MODEL=gpt-5.5
ANTHROPIC_DEFAULT_HAIKU_MODEL=gpt-5.4-mini
ANTHROPIC_DEFAULT_SONNET_MODEL=gpt-5.4
ANTHROPIC_DEFAULT_OPUS_MODEL=gpt-5.5
```

Gemini model aliases exposed to Claude Code:

```sh
ANTHROPIC_BASE_URL=http://127.0.0.1:4000
ANTHROPIC_API_KEY=litellm-local-test-key
ANTHROPIC_MODEL=gemini-3.1-pro-preview
ANTHROPIC_DEFAULT_HAIKU_MODEL=gemini-3.1-flash-lite-preview
ANTHROPIC_DEFAULT_SONNET_MODEL=gemini-3-flash
ANTHROPIC_DEFAULT_OPUS_MODEL=gemini-3.1-pro-preview
```

## Auto Start on Login

Use the manager instead of shell startup files:

```sh
python3 -m proxy_stack install-autostart
```

This creates a user login item for the current OS:

- macOS: `~/Library/LaunchAgents/com.yingfanqaq.local-ai-proxy-stack.plist`
- Linux: `~/.config/autostart/com.yingfanqaq.local-ai-proxy-stack.desktop`
- Windows: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`

Remove it with:

```sh
python3 -m proxy_stack uninstall-autostart
```

## Logs

When started by the cross-platform manager, logs are under the user state directory:

```sh
tail -f "$HOME/Library/Application Support/LocalAIProxyStack/logs/codex-chat-proxy.log"
tail -f "$HOME/Library/Application Support/LocalAIProxyStack/logs/gemini-genai-proxy.log"
tail -f "$HOME/Library/Application Support/LocalAIProxyStack/logs/litellm-two-proxy.log"
```

On Linux use `~/.local/state/local-ai-proxy-stack/logs/`; on Windows use `%LOCALAPPDATA%\LocalAIProxyStack\logs\`.

## Health Checks

```sh
curl http://127.0.0.1:39121/health
curl http://127.0.0.1:39122/health
curl http://127.0.0.1:4000/health/readiness
```

## Smoke Tests

Codex proxy:

```sh
curl -sS -H 'Authorization: Bearer codex-proxy-local-key' \
  -H 'Content-Type: application/json' \
  -d '{"model":"gpt-5.5","messages":[{"role":"user","content":"Reply exactly OK."}],"stream":false}' \
  http://127.0.0.1:39121/v1/chat/completions
```

Gemini proxy:

```sh
curl -sS -H 'x-goog-api-key: gemini-proxy-local-key' \
  -H 'Content-Type: application/json' \
  -d '{"contents":[{"role":"user","parts":[{"text":"Reply exactly OK."}]}]}' \
  'http://127.0.0.1:39122/v1beta/models/gemini-3-flash-preview:generateContent'
```

LiteLLM Anthropic-compatible route:

```sh
curl -sS -H 'x-api-key: litellm-local-test-key' \
  -H 'anthropic-version: 2023-06-01' \
  -H 'content-type: application/json' \
  -d '{"model":"gpt-5.5","max_tokens":64,"messages":[{"role":"user","content":"Reply exactly OK."}]}' \
  http://127.0.0.1:4000/v1/messages
```

For `codex-cli`, define a custom provider so the CLI really uses the proxy:

```sh
OPENAI_API_KEY=codex-proxy-local-key codex exec \
  -c 'model_provider="codex_proxy"' \
  -c 'model_providers.codex_proxy.name="Codex Proxy"' \
  -c 'model_providers.codex_proxy.base_url="http://127.0.0.1:39121/v1"' \
  -c 'model_providers.codex_proxy.env_key="OPENAI_API_KEY"' \
  -c 'model_providers.codex_proxy.wire_api="responses"' \
  -c 'model_providers.codex_proxy.requires_openai_auth=false' \
  --cd /tmp --skip-git-repo-check --sandbox read-only --ephemeral \
  --model gpt-5.5 \
  'Reply exactly OK.'
```

For `gemini-cli`:

```sh
GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:39122 \
GEMINI_API_KEY=gemini-proxy-local-key \
gemini -m gemini-3-flash-preview -p 'Reply exactly OK.' --output-format text
```

## Release Builds

Pushing a tag like `v0.1.0` triggers `.github/workflows/release.yml`, which builds macOS, Linux, and Windows zip artifacts with PyInstaller and attaches them to the GitHub release.
