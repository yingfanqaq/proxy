# proxyEverywhere

proxyEverywhere is a local cross-platform proxy flow manager for AI coding CLIs and API adapters.

The core idea is no longer a fixed pipeline like `Codex + Gemini -> LiteLLM -> Anthropic`. Instead, each conversion is a flow:

```text
Start node -> LiteLLM node -> Output node(s)
```

Start nodes can be local proxy services or an external relay endpoint. Output nodes define the API format and port you want to expose.

## Built-in Start Nodes

- Codex local proxy: exposes OpenAI-compatible `/v1/chat/completions` and `/v1/responses`, backed by Codex OAuth.
- Gemini local proxy: exposes Gemini Developer API-compatible `/v1beta`, backed by Gemini CLI OAuth.
- Claude Code local proxy: exposes Anthropic Messages-compatible `/v1/messages`, backed by the logged-in local `claude` CLI.
- External relay: use an existing `BASE_URL` and API key instead of starting a local source proxy.

## Built-in Middle Node

- LiteLLM is currently the only middle node.
- Release builds bundle LiteLLM as a Python dependency inside the app, so users should not need to install a separate `litellm` command.
- Source/development mode can still use a local `litellm` executable if you run from this repository.

## Built-in Output Formats

- Anthropic-compatible endpoint, useful for Claude Code via `ANTHROPIC_BASE_URL`.
- OpenAI-compatible endpoint, useful for tools expecting `OPENAI_BASE_URL`.

LiteLLM usually exposes both OpenAI-compatible and Anthropic-compatible routes on the same service port; proxyEverywhere still records the intended output format on each flow so the UI and generated snippets stay clear.

## Default Flows

Enabled by default:

- `Codex to Anthropic`: Codex local OpenAI-compatible proxy -> LiteLLM -> Anthropic-compatible output on `4000`.
- `Gemini to Anthropic`: Gemini local GenAI proxy -> LiteLLM -> Anthropic-compatible output on `4000`.
- `Claude Code to Anthropic`: Claude Code local Anthropic-compatible proxy -> LiteLLM -> Anthropic-compatible output on `4000`.

Included as a disabled template:

- `Claude Code to OpenAI`: Claude Code local Anthropic-compatible proxy -> LiteLLM -> OpenAI-compatible output on `4001`.

## Ports

Default local source ports:

```sh
Codex proxy       http://127.0.0.1:39121/v1
Gemini proxy      http://127.0.0.1:39122
Claude Code proxy http://127.0.0.1:39123
Settings page     http://127.0.0.1:39200
```

Default output port:

```sh
LiteLLM output    http://127.0.0.1:4000
```

## Settings and Flow Designer

Open the settings page:

```sh
http://127.0.0.1:39200
```

The page includes:

- Service status and logs.
- Ports, API keys, executable paths, and autostart settings.
- A Dify-style flow canvas where start, LiteLLM, and output nodes can be moved by dragging.
- Editable Flow JSON for exact flow definitions.
- Environment snippets for Claude Code, OpenAI-compatible clients, and Gemini-compatible clients.

## Running From Source

Install Python dependencies:

```sh
cd /Users/yingfanqaq/mycodelibrary/proxy
python3 -m pip install -r requirements-app.txt
```

Start everything:

```sh
python3 -m proxy_stack start
```

Open the tray app and settings page:

```sh
python3 -m proxy_stack tray --start-services --open-settings
```

Useful commands:

```sh
python3 -m proxy_stack status
python3 -m proxy_stack restart
python3 -m proxy_stack env
python3 -m proxy_stack install-autostart
python3 -m proxy_stack uninstall-autostart
```

## Autostart

proxyEverywhere creates user-level startup entries:

- macOS: `~/Library/LaunchAgents/com.yingfanqaq.proxyeverywhere.plist` plus per-service LaunchAgents.
- Linux: `~/.config/autostart/com.yingfanqaq.proxyeverywhere.desktop`.
- Windows: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

Install autostart:

```sh
python3 -m proxy_stack install-autostart
```

Remove autostart:

```sh
python3 -m proxy_stack uninstall-autostart
```

## Config and Logs

Config paths:

- macOS: `~/Library/Application Support/proxyEverywhere/config.json`
- Linux: `~/.config/proxyeverywhere/config.json`
- Windows: `%APPDATA%\proxyEverywhere\config.json`

Log paths:

- macOS: `~/Library/Application Support/proxyEverywhere/logs/`
- Linux: `~/.local/state/proxyeverywhere/logs/`
- Windows: `%LOCALAPPDATA%\proxyEverywhere\logs\`

## Client Snippets

Print snippets generated from the current flow config:

```sh
python3 -m proxy_stack env
```

Claude Code via Codex/Gemini/Claude flows:

```sh
unset ANTHROPIC_AUTH_TOKEN
export ANTHROPIC_BASE_URL=http://127.0.0.1:4000
export ANTHROPIC_API_KEY=litellm-local-test-key
export ANTHROPIC_MODEL=gpt-5.5
```

OpenAI-compatible output from a flow can be used with:

```sh
export OPENAI_BASE_URL=http://127.0.0.1:4001/v1
export OPENAI_API_KEY=litellm-local-test-key
```

## Release Builds

Pushing a tag like `v0.2.0` triggers `.github/workflows/release.yml`, which builds macOS, Linux, and Windows zip artifacts with PyInstaller and attaches them to the GitHub release.

The release app bundles:

- proxyEverywhere tray/settings code.
- Codex, Gemini, and Claude Code local proxy services.
- LiteLLM and Python runtime dependencies collected by PyInstaller.

It does not bundle the upstream Codex, Gemini, or Claude CLIs themselves; enable a local source node only after that CLI is installed and logged in on the machine.

That means normal users should download the platform-specific zip and run the app, without separately installing LiteLLM.
