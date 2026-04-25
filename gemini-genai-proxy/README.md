# gemini-genai-proxy

Tiny local Gemini Developer API compatible proxy backed by Gemini CLI OAuth.

It exposes:

- `GET /v1beta/models`
- `POST /v1beta/models/{model}:generateContent`
- `POST /v1beta/models/{model}:streamGenerateContent`
- `POST /v1beta/models/{model}:countTokens`

Default env:

```sh
export GOOGLE_GEMINI_BASE_URL="http://127.0.0.1:39122"
export GEMINI_API_KEY="gemini-proxy-local-key"
```

Run:

```sh
./run.sh
```

The service reads Gemini CLI credentials from `~/.gemini/oauth_creds.json`.
