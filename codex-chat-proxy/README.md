# codex-chat-proxy

Tiny local OpenAI-compatible Chat Completions proxy backed by Codex OAuth.

It exposes:

- `GET /v1/models`
- `POST /v1/chat/completions`

Default env:

```sh
export OPENAI_BASE_URL="http://127.0.0.1:39121/v1"
export OPENAI_API_KEY="codex-proxy-local-key"
```

Run:

```sh
./run.sh
```

The service reads Codex credentials from `~/.codex/auth.json`.
