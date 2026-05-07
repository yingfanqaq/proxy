from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse


APP_NAME = "claude-code-api-adapter"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "39124"))
LOCAL_API_KEY = os.environ.get("CLAUDE_CODE_API_LOCAL_KEY", "claude-code-api-local-key")
UPSTREAM_BASE_URL = os.environ.get("CLAUDE_CODE_API_BASE_URL", "").strip().rstrip("/")
UPSTREAM_API_KEY = os.environ.get("CLAUDE_CODE_API_KEY", "").strip()
ANTHROPIC_VERSION = os.environ.get("ANTHROPIC_VERSION", "2023-06-01")
REQUEST_TIMEOUT = int(os.environ.get("CLAUDE_CODE_API_TIMEOUT", "900"))
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
EFFORT_ALIASES = {"minimal": "low"}
MODEL_ALIASES = {
    "claude-code": "claude-sonnet-4-6",
    "claude-api": "claude-sonnet-4-6",
    "claude-code-sonnet": "claude-sonnet-4-6",
    "sonnet": "claude-sonnet-4-6",
    "claude-code-opus": "claude-opus-4-7",
    "opus": "claude-opus-4-7",
    "claude-code-haiku": "claude-haiku-4-5",
    "haiku": "claude-haiku-4-5",
    "claude-code-sonnet-4-6": "claude-sonnet-4-6",
    "claude-code-opus-4-7": "claude-opus-4-7",
    "claude-code-opus-4-6": "claude-opus-4-6",
    "claude-code-haiku-4-5": "claude-haiku-4-5",
}


app = FastAPI(title=APP_NAME)


def model_catalog() -> list[str]:
    base = [
        "claude-code",
        "claude-code-sonnet",
        "claude-code-opus",
        "claude-code-haiku",
        "sonnet",
        "opus",
        "haiku",
        "claude-sonnet-4-6",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-haiku-4-5",
        "claude-code-sonnet-4-6",
        "claude-code-opus-4-7",
        "claude-code-opus-4-6",
        "claude-code-haiku-4-5",
    ]
    efforts: list[str] = []
    for model in ("claude-code-sonnet", "claude-code-sonnet-4-6"):
        efforts.extend(f"{model}-{effort}" for effort in ("low", "medium", "high"))
    for model in ("claude-code-opus", "claude-code-opus-4-7"):
        efforts.extend(f"{model}-{effort}" for effort in ("low", "medium", "high", "xhigh"))
    efforts.extend(f"claude-code-opus-4-6-{effort}" for effort in ("low", "medium", "high", "max"))
    return list(dict.fromkeys([*base, *efforts]))


MODELS = [
    item.strip()
    for item in os.environ.get("CLAUDE_CODE_API_MODELS", ",".join(model_catalog())).split(",")
    if item.strip()
]


def require_auth(authorization: str | None, x_api_key: str | None) -> None:
    if not LOCAL_API_KEY:
        return
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if x_api_key:
        token = x_api_key
    if token != LOCAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def normalize_effort(value: Any) -> str | None:
    effort = str(value or "").strip().lower()
    effort = EFFORT_ALIASES.get(effort, effort)
    return effort if effort in EFFORT_LEVELS else None


def split_model_effort(model: Any) -> tuple[str, str | None]:
    text = str(model or "claude-code").strip()
    for effort in EFFORT_LEVELS:
        suffix = f"-{effort}"
        if text.endswith(suffix):
            return text[: -len(suffix)], effort
    return text, None


def normalize_model_request(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    raw_model, suffix_effort = split_model_effort(updated.get("model"))
    updated["model"] = MODEL_ALIASES.get(raw_model, raw_model)
    effort = normalize_effort(updated.get("reasoning_effort")) or suffix_effort
    output_config = updated.get("output_config")
    if effort and not (isinstance(output_config, dict) and output_config.get("effort")):
        output_config = dict(output_config) if isinstance(output_config, dict) else {}
        output_config["effort"] = effort
        updated["output_config"] = output_config
    updated.pop("reasoning_effort", None)
    return updated


def upstream_url(path: str) -> str:
    if not UPSTREAM_BASE_URL:
        raise HTTPException(status_code=400, detail="Upstream base URL is not configured")
    return f"{UPSTREAM_BASE_URL}/{path.lstrip('/')}"


def upstream_headers(request: Request, json_body: bool) -> dict[str, str]:
    headers: dict[str, str] = {}
    if json_body:
        headers["Content-Type"] = "application/json"
    headers["x-api-key"] = UPSTREAM_API_KEY
    headers["Authorization"] = f"Bearer {UPSTREAM_API_KEY}"
    headers["anthropic-version"] = request.headers.get("anthropic-version", ANTHROPIC_VERSION)
    for key in ("anthropic-beta", "anthropic-dangerous-direct-browser-access"):
        if request.headers.get(key):
            headers[key] = request.headers[key]
    return headers


def proxy_response(url: str, method: str, headers: dict[str, str], body: bytes | None, stream: bool) -> Response:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return Response(content=raw, status_code=exc.code, media_type=exc.headers.get("Content-Type", "application/json"))

    content_type = resp.headers.get("Content-Type", "application/json")
    if stream:
        def iter_bytes():
            with resp:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(iter_bytes(), status_code=resp.status, media_type=content_type)
    raw = resp.read()
    resp.close()
    return Response(content=raw, status_code=resp.status, media_type=content_type)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": APP_NAME,
        "upstream_base_url": UPSTREAM_BASE_URL,
        "models": MODELS,
    }


@app.get("/v1/models")
async def list_models(authorization: str | None = Header(None), x_api_key: str | None = Header(None)) -> dict[str, Any]:
    require_auth(authorization, x_api_key)
    now = int(time.time())
    return {
        "object": "list",
        "data": [{"id": model, "object": "model", "created": now, "owned_by": "claude-code-api"} for model in MODELS],
    }


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_anthropic(path: str, request: Request, authorization: str | None = Header(None), x_api_key: str | None = Header(None)) -> Response:
    require_auth(authorization, x_api_key)
    method = request.method.upper()
    raw_body = await request.body()
    stream = False
    if method == "POST" and path == "messages" and raw_body:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            payload = normalize_model_request(payload)
            stream = bool(payload.get("stream"))
            raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return proxy_response(upstream_url(f"/v1/{path}"), method, upstream_headers(request, bool(raw_body)), raw_body or None, stream)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
