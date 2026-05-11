from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse


APP_NAME = "claude-code-api-adapter"
logging.basicConfig(level=os.environ.get("CLAUDE_CODE_API_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(APP_NAME)
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "39124"))
LOCAL_API_KEY = os.environ.get("CLAUDE_CODE_API_LOCAL_KEY", "claude-code-api-local-key")
UPSTREAM_BASE_URL = os.environ.get("CLAUDE_CODE_API_BASE_URL", "").strip().rstrip("/")
UPSTREAM_API_KEY = os.environ.get("CLAUDE_CODE_API_KEY", "").strip()
ANTHROPIC_VERSION = os.environ.get("ANTHROPIC_VERSION", "2023-06-01")
REQUEST_TIMEOUT = int(os.environ.get("CLAUDE_CODE_API_TIMEOUT", "900"))
UPSTREAM_RETRIES = max(0, int(os.environ.get("CLAUDE_CODE_API_RETRIES", "2")))
HAIKU_FALLBACK_MODEL = os.environ.get("CLAUDE_CODE_API_HAIKU_FALLBACK_MODEL", "claude-sonnet-4-6").strip()
LOCAL_TITLE_GENERATION = os.environ.get("CLAUDE_CODE_API_LOCAL_TITLE_GENERATION", "1").strip().lower() not in {"0", "false", "no"}
TITLE_GENERATION_TIMEOUT = int(os.environ.get("CLAUDE_CODE_API_TITLE_TIMEOUT", "25"))
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
    "claude-3-5-sonnet-latest": "claude-sonnet-4-6",
    "claude-3-7-sonnet-latest": "claude-sonnet-4-6",
    "claude-sonnet-4": "claude-sonnet-4-6",
    "claude-opus-4": "claude-opus-4-7",
    "claude-haiku-4": "claude-haiku-4-5",
    "claude-3-5-haiku-latest": "claude-haiku-4-5",
    "claude-3-haiku-20240307": "claude-haiku-4-5",
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
        efforts.extend(f"{model}-{effort}" for effort in ("low", "medium", "high", "max"))
    for model in ("claude-code-opus", "claude-code-opus-4-7"):
        efforts.extend(f"{model}-{effort}" for effort in EFFORT_LEVELS)
    efforts.extend(f"claude-code-opus-4-6-{effort}" for effort in ("low", "medium", "high", "max"))
    return list(dict.fromkeys([*base, *efforts]))


MODELS = [
    item.strip()
    for item in os.environ.get("CLAUDE_CODE_API_MODELS", ",".join(model_catalog())).split(",")
    if item.strip()
]


def now_ms() -> int:
    return int(time.perf_counter() * 1000)


def elapsed_ms(start_ms: int) -> int:
    return now_ms() - start_ms


def truncate_detail(value: str, limit: int = 1200) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + f"... <truncated {len(value) - limit} chars>"


def content_text_chars(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, str):
                total += len(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    total += len(str(item.get("text", "")))
                elif item.get("type") == "tool_result":
                    total += content_text_chars(item.get("content"))
        return total
    return len(str(content or ""))


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "tool_result":
                    parts.append(content_text(item.get("content")))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def estimate_input_tokens(payload: dict[str, Any]) -> int:
    text_chars = content_text_chars(payload.get("system"))
    images = 0
    messages = payload.get("messages", [])
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            text_chars += content_text_chars(content)
            if isinstance(content, list):
                images += sum(1 for item in content if isinstance(item, dict) and item.get("type") == "image")
    message_overhead = len(messages) * 4 if isinstance(messages, list) else 0
    return max(1, text_chars // 4 + images * 1200 + message_overhead)


def payload_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    system_text = content_text(payload.get("system"))
    if system_text:
        parts.append(system_text)
    messages = payload.get("messages", [])
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict):
                text = content_text(message.get("content"))
                if text:
                    parts.append(text)
    return "\n".join(parts)


def is_title_generation_request(payload: dict[str, Any]) -> bool:
    text = payload_text(payload)
    markers = (
        "succinct title for an agent chat session",
        "wrap the title in <title> tags",
        "<description>",
        "</description>",
        "Please generate a title for this session.",
    )
    return LOCAL_TITLE_GENERATION and all(marker in text for marker in markers)


def extract_title_description(payload: dict[str, Any]) -> str:
    text = payload_text(payload)
    match = re.search(r"<description>(.*?)</description>", text, re.IGNORECASE | re.DOTALL)
    description = match.group(1) if match else text
    description = html.unescape(description)
    description = re.sub(r"<[^>]+>", " ", description)
    description = re.sub(r"```.*?```", " ", description, flags=re.DOTALL)
    description = re.sub(r"[ \t]+", " ", description)
    description = re.sub(r"\n{3,}", "\n\n", description)
    return description.strip()


def is_bad_title_candidate(value: str) -> bool:
    compact = re.sub(r"\s+", " ", value).strip(" -:：,.，").lower()
    if not compact:
        return True
    bad_prefixes = (
        "contain information about the user",
        "contains information about the user",
        "information about the user",
        "the user prefers",
        "the user likes",
        "the user is",
        "memory about the user",
        "user memory",
        "system prompt",
        "application details",
        "claude behavior",
    )
    return any(compact.startswith(prefix) for prefix in bad_prefixes)


def title_source_candidates(description: str) -> list[str]:
    text = description.strip()
    if not text:
        return []
    candidates: list[str] = []
    user_pattern = re.compile(
        r"(?:^|\n)\s*(?:user|human|用户|用户消息|initial user message|user message)\s*[:：]\s*(.+?)(?=\n\s*(?:assistant|claude|system|user|human|助手|系统|用户)\s*[:：]|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    candidates.extend(match.strip() for match in reversed(user_pattern.findall(text)))
    candidates.extend(line.strip() for line in text.splitlines())
    candidates.extend(part.strip() for part in re.split(r"[。！？!?；;]+", text))
    candidates.append(text)
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = re.sub(r"\s+", " ", candidate).strip(" -:：,.，")
        candidate = re.sub(r"\bcontains? information about the user'?s?.*$", "", candidate, flags=re.IGNORECASE).strip(" -:：,.，")
        if not candidate or is_bad_title_candidate(candidate):
            continue
        key = candidate.lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def compact_title_from_candidate(candidate: str) -> str:
    text = candidate.strip()
    if not text:
        return ""
    text = re.sub(r"^(please|can you|could you|help me|let'?s)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(请你|请|帮我|麻烦|可以|你看|我想|我希望|接下来|关于)", "", text).strip()
    first_sentence = re.split(r"[。！？!?；;\n\r]+", text, 1)[0].strip(" -:：,.，")
    if not first_sentence:
        first_sentence = text
    if re.search(r"[\u4e00-\u9fff]", first_sentence):
        if first_sentence in {"你好", "您好", "嗨", "哈喽"}:
            return "简单问候"
        tokens = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9][A-Za-z0-9_+#./-]*", first_sentence)
        if tokens:
            title = " ".join(tokens[:6])
            return title[:30].strip() or "新会话"
        return first_sentence[:22].strip() or "新会话"
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_+#./-]*", first_sentence)
    if not words:
        return "New chat"
    if len(words) == 1 and words[0].lower() in {"hi", "hello", "hey"}:
        return "Quick greeting"
    return " ".join(words[:6])


def local_title_from_description(description: str) -> str:
    for candidate in title_source_candidates(description):
        title = compact_title_from_candidate(candidate)
        if title and not is_bad_title_candidate(title):
            return title
    return "New chat"


def title_generation_body(payload: dict[str, Any], model: str) -> dict[str, Any]:
    title = local_title_from_description(extract_title_description(payload))
    text = f"<title>{html.escape(title, quote=False)}</title>"
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": model or str(payload.get("model") or "claude-code-haiku"),
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": estimate_input_tokens(payload),
            "output_tokens": max(1, len(text) // 4),
        },
    }


def title_generation_sse(body: dict[str, Any]) -> str:
    message = dict(body)
    text = ""
    if body.get("content") and isinstance(body["content"], list):
        first = body["content"][0]
        if isinstance(first, dict):
            text = str(first.get("text", ""))
    message["content"] = []
    message["stop_reason"] = None
    message["stop_sequence"] = None
    message["usage"] = {"input_tokens": body.get("usage", {}).get("input_tokens", 1), "output_tokens": 0}
    events = [
        ("message_start", {"type": "message_start", "message": message}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": body.get("usage", {}).get("output_tokens", 1)}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for event, data in events)


def is_upstream_failure(response: Response) -> bool:
    status_code = getattr(response, "status_code", 0) or 0
    return int(status_code) >= 500


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
    normalized_model = MODEL_ALIASES.get(raw_model, raw_model)
    if HAIKU_FALLBACK_MODEL and normalized_model == "claude-haiku-4-5":
        LOGGER.info("adapter_request phase=model_fallback model_raw=%s model=%s fallback=%s", raw_model, normalized_model, HAIKU_FALLBACK_MODEL)
        normalized_model = HAIKU_FALLBACK_MODEL
    updated["model"] = normalized_model
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
    headers["User-Agent"] = request.headers.get("user-agent", "claude-code/1.0 proxyEverywhere")
    headers["Accept"] = request.headers.get("accept", "application/json")
    headers["x-api-key"] = UPSTREAM_API_KEY
    headers["Authorization"] = f"Bearer {UPSTREAM_API_KEY}"
    headers["anthropic-version"] = request.headers.get("anthropic-version", ANTHROPIC_VERSION)
    for key in ("anthropic-beta", "anthropic-dangerous-direct-browser-access"):
        if request.headers.get(key):
            headers[key] = request.headers[key]
    return headers


def proxy_response(url: str, method: str, headers: dict[str, str], body: bytes | None, stream: bool, request_id: str = "-") -> Response:
    return proxy_response_with_timeout(url, method, headers, body, stream, REQUEST_TIMEOUT, request_id)


def proxy_response_with_timeout(url: str, method: str, headers: dict[str, str], body: bytes | None, stream: bool, timeout: int, request_id: str = "-") -> Response:
    last_error: urllib.error.URLError | None = None
    for attempt in range(UPSTREAM_RETRIES + 1):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            LOGGER.info(
                "adapter_request id=%s phase=upstream_http_error status=%s attempt=%s url=%s body_chars=%s",
                request_id,
                exc.code,
                attempt + 1,
                url,
                len(raw or b""),
            )
            return Response(content=raw, status_code=exc.code, media_type=exc.headers.get("Content-Type", "application/json"))
        except urllib.error.URLError as exc:
            last_error = exc
            detail = str(getattr(exc, "reason", exc))
            LOGGER.warning(
                "adapter_request id=%s phase=upstream_url_error attempt=%s/%s url=%s detail=%s",
                request_id,
                attempt + 1,
                UPSTREAM_RETRIES + 1,
                url,
                truncate_detail(detail),
            )
            if attempt < UPSTREAM_RETRIES:
                time.sleep(min(1.0, 0.25 * (attempt + 1)))
                continue
            break

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

    detail = str(getattr(last_error, "reason", last_error)) if last_error else "upstream request failed"
    return JSONResponse(
        {
            "error": {
                "type": "upstream_connection_error",
                "message": "Claude Code API upstream connection failed after retries.",
                "detail": truncate_detail(detail),
            }
        },
        status_code=502,
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": APP_NAME}


@app.get("/info")
async def info() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": APP_NAME,
        "upstream_base_url": UPSTREAM_BASE_URL,
        "models": MODELS,
        "haiku_fallback_model": HAIKU_FALLBACK_MODEL,
        "local_title_generation": LOCAL_TITLE_GENERATION,
    }


@app.get("/v1/models")
async def list_models(authorization: str | None = Header(None), x_api_key: str | None = Header(None)) -> dict[str, Any]:
    require_auth(authorization, x_api_key)
    now = int(time.time())
    return {
        "object": "list",
        "data": [{"id": model, "object": "model", "created": now, "owned_by": "claude-code-api"} for model in MODELS],
    }

@app.post("/v1/messages/count_tokens")
async def count_message_tokens(request: Request, authorization: str | None = Header(None), x_api_key: str | None = Header(None)) -> dict[str, int]:
    require_auth(authorization, x_api_key)
    request_id = uuid.uuid4().hex[:12]
    payload = await request.json()
    tokens = estimate_input_tokens(payload if isinstance(payload, dict) else {})
    model = payload.get("model") if isinstance(payload, dict) else ""
    LOGGER.info("adapter_request id=%s phase=count_tokens model=%s input_tokens=%s", request_id, model or "", tokens)
    return {"input_tokens": tokens}


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_anthropic(path: str, request: Request, authorization: str | None = Header(None), x_api_key: str | None = Header(None)) -> Response:
    require_auth(authorization, x_api_key)
    request_id = uuid.uuid4().hex[:12]
    start_ms = now_ms()
    method = request.method.upper()
    raw_body = await request.body()
    stream = False
    model_raw = ""
    model = ""
    payload: dict[str, Any] | None = None
    title_generation = False
    if method == "POST" and path == "messages" and raw_body:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            model_raw = str(payload.get("model") or "")
            payload = normalize_model_request(payload)
            model = str(payload.get("model") or "")
            stream = bool(payload.get("stream"))
            if is_title_generation_request(payload):
                title_generation = True
            raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    LOGGER.info(
        "adapter_request id=%s phase=request_start method=%s path=/v1/%s stream=%s model_raw=%s model=%s body_bytes=%s",
        request_id,
        method,
        path,
        stream,
        model_raw,
        model,
        len(raw_body or b""),
    )
    upstream_timeout = TITLE_GENERATION_TIMEOUT if title_generation else REQUEST_TIMEOUT
    response = await asyncio.to_thread(
        proxy_response_with_timeout,
        upstream_url(f"/v1/{path}"),
        method,
        upstream_headers(request, bool(raw_body)),
        raw_body or None,
        stream,
        upstream_timeout,
        request_id,
    )
    if title_generation and payload is not None and is_upstream_failure(response):
        LOGGER.warning(
            "adapter_request id=%s phase=title_generation_upstream_failed status=%s fallback=local",
            request_id,
            getattr(response, "status_code", ""),
        )
        body = title_generation_body(payload, model_raw or model)
        response = Response(content=title_generation_sse(body), status_code=200, media_type="text/event-stream") if stream else JSONResponse(body)
    LOGGER.info(
        "adapter_request id=%s phase=request_done elapsed_ms=%s status=%s path=/v1/%s",
        request_id,
        elapsed_ms(start_ms),
        getattr(response, "status_code", ""),
        path,
    )
    return response


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
