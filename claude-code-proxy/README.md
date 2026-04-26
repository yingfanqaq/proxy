# claude-code-proxy

Anthropic Messages API compatible proxy backed by the local `claude` CLI login.

It is intentionally small: it accepts `/v1/messages`, converts the request into a Claude Code print-mode prompt, runs `claude -p`, and returns an Anthropic-style message response.

```sh
CLAUDE_PROXY_API_KEY=claude-proxy-local-key ./run.sh
```

Default endpoint:

```sh
ANTHROPIC_BASE_URL=http://127.0.0.1:39123
ANTHROPIC_API_KEY=claude-proxy-local-key
```
