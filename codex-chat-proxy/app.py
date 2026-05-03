from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse


APP_NAME = "codex-chat-proxy"
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 39121
DEFAULT_PROXY_KEY = "codex-proxy-local-key"
DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_OPENAI_RESPONSES_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TOKEN_URL = "https://auth.openai.com/oauth/token"
DEFAULT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_CODEX_CLIENT_VERSION = "0.125.0"
DEFAULT_MODELS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.2",
]


def env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


PROXY_KEY = env("CODEX_PROXY_API_KEY", DEFAULT_PROXY_KEY)
CODEX_BASE_URL = env("CODEX_BASE_URL", DEFAULT_CODEX_BASE_URL).rstrip("/")
OPENAI_RESPONSES_BASE_URL = env("CODEX_OPENAI_RESPONSES_BASE_URL", DEFAULT_OPENAI_RESPONSES_BASE_URL).rstrip("/")
TOKEN_URL = env("CODEX_OAUTH_TOKEN_URL", DEFAULT_TOKEN_URL)
CLIENT_ID = env("CODEX_OAUTH_CLIENT_ID", DEFAULT_CLIENT_ID)
VERSION_RE = re.compile("([0-9]+\\.[0-9]+\\.[0-9]+(?:[-+][^\\s]+)?)")


def version_key(version: str) -> tuple[int, int, int]:
    parts = VERSION_RE.search(version)
    if not parts:
        return (0, 0, 0)
    major, minor, patch = parts.group(1).split(".")[:3]
    return (int(major), int(minor), int(patch))


def detect_codex_client_version() -> str:
    configured = os.environ.get("CODEX_CLIENT_VERSION", "").strip()
    if configured:
        return configured

    codex_bin = os.environ.get("CODEX_CLI_PATH") or shutil.which("codex")
    if codex_bin:
        try:
            result = subprocess.run(
                [codex_bin, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = "\n".join(part for part in (result.stdout, result.stderr) if part)
            match = VERSION_RE.search(output)
            if match:
                detected = match.group(1)
                if version_key(detected) >= version_key(DEFAULT_CODEX_CLIENT_VERSION):
                    return detected
        except Exception:
            pass
    return DEFAULT_CODEX_CLIENT_VERSION


CODEX_CLIENT_VERSION: str | None = None


def codex_client_version() -> str:
    global CODEX_CLIENT_VERSION
    if CODEX_CLIENT_VERSION is None:
        CODEX_CLIENT_VERSION = detect_codex_client_version()
    return CODEX_CLIENT_VERSION


AUTH_PATH = Path(env("CODEX_AUTH_PATH", str(Path.home() / ".codex" / "auth.json"))).expanduser()
MODEL_IDS = [
    item.strip()
    for item in env("CODEX_PROXY_MODELS", ",".join(DEFAULT_MODELS)).split(",")
    if item.strip()
]

@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await http_client.aclose()


app = FastAPI(title=APP_NAME, lifespan=lifespan)
http_client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=30.0))
credential_lock = asyncio.Lock()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} did not contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def decode_jwt(token: str | None) -> dict[str, Any]:
    if not token or "." not in token:
        return {}
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(part.encode()).decode())
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def token_expiring(token: str | None) -> bool:
    claims = decode_jwt(token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return float(exp) <= time.time() + 120


async def load_auth() -> dict[str, Any]:
    if not AUTH_PATH.exists():
        raise HTTPException(status_code=401, detail=f"Codex auth file not found: {AUTH_PATH}")
    auth = await asyncio.to_thread(read_json, AUTH_PATH)
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        raise HTTPException(status_code=401, detail="Codex auth file has no access token")
    if token_expiring(tokens.get("access_token")):
        auth = await refresh_auth(auth)
    return auth


def auth_info_from_payload(auth: dict[str, Any]) -> dict[str, Any]:
    tokens = auth.get("tokens")
    if isinstance(tokens, dict) and isinstance(tokens.get("access_token"), str) and tokens["access_token"]:
        return {"mode": "chatgpt", "auth": auth}
    api_key = auth.get("OPENAI_API_KEY") or auth.get("openai_api_key")
    if isinstance(api_key, str) and api_key:
        return {"mode": "openai_api_key", "api_key": api_key}
    return {}


async def load_auth_info() -> dict[str, Any]:
    configured_api_key = os.environ.get("CODEX_OPENAI_API_KEY", "").strip()
    if configured_api_key:
        return {"mode": "openai_api_key", "api_key": configured_api_key}
    if not AUTH_PATH.exists():
        raise HTTPException(status_code=401, detail=f"Codex auth file not found: {AUTH_PATH}")
    auth = await asyncio.to_thread(read_json, AUTH_PATH)
    info = auth_info_from_payload(auth)
    if not info:
        raise HTTPException(status_code=401, detail="Codex auth file has neither ChatGPT tokens nor OPENAI_API_KEY")
    if info["mode"] == "chatgpt":
        tokens = auth["tokens"]
        if token_expiring(tokens.get("access_token")):
            auth = await refresh_auth(auth)
            info = {"mode": "chatgpt", "auth": auth}
    return info


async def refresh_auth(auth: dict[str, Any]) -> dict[str, Any]:
    async with credential_lock:
        current = await asyncio.to_thread(read_json, AUTH_PATH)
        tokens = current.get("tokens") if isinstance(current.get("tokens"), dict) else {}
        if not token_expiring(tokens.get("access_token")):
            return current
        refresh_token = tokens.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            return current
        response = await http_client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
                "scope": "openid profile email offline_access",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "codex-chat-proxy",
            },
        )
        response.raise_for_status()
        payload = response.json()
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            return current
        updated_tokens = {
            **tokens,
            "access_token": access_token,
            "refresh_token": payload.get("refresh_token") or refresh_token,
            "id_token": payload.get("id_token") or tokens.get("id_token"),
        }
        account_id = decode_jwt(updated_tokens.get("id_token") or access_token).get("sub")
        if isinstance(account_id, str) and account_id:
            updated_tokens["account_id"] = account_id
        updated = {
            **current,
            "tokens": updated_tokens,
            "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        await asyncio.to_thread(write_json, AUTH_PATH, updated)
        return updated


async def access_token_and_account() -> tuple[str, str | None]:
    info = await load_auth_info()
    if info.get("mode") != "chatgpt":
        raise HTTPException(status_code=401, detail="ChatGPT backend requests require Codex OAuth tokens")
    auth = info["auth"]
    tokens = auth["tokens"]
    access_token = tokens["access_token"]
    claims = decode_jwt(tokens.get("id_token") or access_token)
    auth_claims = claims.get("https://api.openai.com/auth")
    chatgpt_account_id = None
    if isinstance(auth_claims, dict):
        value = auth_claims.get("chatgpt_account_id")
        if isinstance(value, str) and value:
            chatgpt_account_id = value
    if not chatgpt_account_id:
        account_id = tokens.get("account_id")
        if isinstance(account_id, str) and account_id:
            chatgpt_account_id = account_id
    return access_token, chatgpt_account_id


def require_proxy_key(request: Request) -> None:
    auth_header = request.headers.get("authorization") or ""
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()
    if PROXY_KEY and token != PROXY_KEY:
        raise HTTPException(status_code=401, detail="Invalid OPENAI_API_KEY for proxy")


def content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return json.dumps(content, ensure_ascii=False)


def convert_tools(tools: Any) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    if not isinstance(tools, list):
        return converted
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") != "function":
            if isinstance(tool.get("type"), str):
                converted.append(dict(tool))
            continue
        fn = tool.get("function")
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not isinstance(name, str) or not name:
            continue
        response_tool = {
            "type": "function",
            "name": name,
            "description": fn.get("description") or "",
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        }
        if "strict" in fn:
            response_tool["strict"] = fn["strict"]
        converted.append(response_tool)
    return converted


def normalize_reasoning_effort(effort: Any) -> Any:
    return "xhigh" if effort == "max" else effort


def copy_present(source: dict[str, Any], target: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        if key in source:
            target[key] = source[key]


def output_token_limit(payload: dict[str, Any]) -> Any:
    for key in ("max_output_tokens", "max_tokens", "max_completion_tokens"):
        if payload.get(key) is not None:
            return payload[key]
    return None


def convert_tool_choice(tool_choice: Any) -> Any:
    if not isinstance(tool_choice, dict):
        return tool_choice
    if tool_choice.get("type") != "function":
        return tool_choice
    function = tool_choice.get("function")
    if isinstance(function, dict) and function.get("name"):
        return {"type": "function", "name": function["name"]}
    return tool_choice


def response_format_to_text(response_format: Any) -> dict[str, Any] | None:
    if not isinstance(response_format, dict):
        return None
    format_type = response_format.get("type")
    if format_type in {"text", "json_object"}:
        return {"format": {"type": format_type}}
    if format_type == "json_schema":
        schema = response_format.get("json_schema")
        if isinstance(schema, dict):
            text_format: dict[str, Any] = {
                "type": "json_schema",
                "name": schema.get("name") or "response",
                "schema": schema.get("schema") or {},
            }
            if "description" in schema:
                text_format["description"] = schema["description"]
            if "strict" in schema:
                text_format["strict"] = schema["strict"]
            return {"format": text_format}
    return {"format": response_format}


def apply_responses_options(source: dict[str, Any], target: dict[str, Any]) -> None:
    copy_present(
        source,
        target,
        (
            "temperature",
            "top_p",
            "background",
            "metadata",
            "include",
            "previous_response_id",
            "conversation",
            "prompt",
            "prompt_cache_key",
            "prompt_cache_retention",
            "safety_identifier",
            "service_tier",
            "store",
            "truncation",
            "max_tool_calls",
            "top_logprobs",
        ),
    )
    if "user" in source and "safety_identifier" not in source:
        target["safety_identifier"] = source["user"]
    limit = output_token_limit(source)
    if limit is not None:
        target["max_output_tokens"] = limit
    if "tool_choice" in source:
        target["tool_choice"] = convert_tool_choice(source["tool_choice"])
    stream_options = source.get("stream_options")
    if isinstance(stream_options, dict):
        allowed_stream_options = {
            key: stream_options[key]
            for key in ("include_obfuscation",)
            if key in stream_options
        }
        if allowed_stream_options:
            target["stream_options"] = allowed_stream_options
    if "text" in source:
        target["text"] = source["text"]
    elif "response_format" in source:
        text = response_format_to_text(source["response_format"])
        if text:
            target["text"] = text
    effort = source.get("reasoning_effort")
    reasoning = source.get("reasoning")
    if isinstance(reasoning, dict):
        reasoning = dict(reasoning)
        if reasoning.get("effort") is not None:
            reasoning["effort"] = normalize_reasoning_effort(reasoning["effort"])
        if effort is not None and not reasoning.get("effort"):
            reasoning["effort"] = normalize_reasoning_effort(effort)
        target["reasoning"] = reasoning
    elif effort is not None:
        target["reasoning"] = {"effort": normalize_reasoning_effort(effort)}


def chat_to_responses(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = content_to_text(message.get("content"))
        if role in {"system", "developer"}:
            if content:
                instructions.append(content)
            continue
        if role == "user":
            input_items.append(
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": content}],
                }
            )
            continue
        if role == "assistant":
            if content:
                input_items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                    }
                )
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    fn = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                    call_id = tool_call.get("id") or f"call_{uuid.uuid4().hex}"
                    input_items.append(
                        {
                            "type": "function_call",
                            "id": call_id,
                            "call_id": call_id,
                            "name": fn.get("name") or "",
                            "arguments": fn.get("arguments") or "{}",
                        }
                    )
            continue
        if role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id") or "",
                    "output": content,
                }
            )

    if not input_items:
        input_items.append(
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "(empty request)"}],
            }
        )

    responses_payload: dict[str, Any] = {
        "model": payload.get("model") or MODEL_IDS[0],
        "input": input_items,
        "stream": True,
        "store": False,
    }
    responses_payload["instructions"] = (
        "\n\n".join(instructions)
        if instructions
        else "You are a helpful coding assistant. Follow the user's instructions."
    )
    tools = convert_tools(payload.get("tools"))
    if tools:
        responses_payload["tools"] = tools
    if isinstance(payload.get("parallel_tool_calls"), bool):
        responses_payload["parallel_tool_calls"] = payload["parallel_tool_calls"]
    apply_responses_options(payload, responses_payload)
    return responses_payload


def chat_chunk(
    *,
    model: str,
    content: str | None = None,
    tool_call: dict[str, Any] | None = None,
    finish_reason: str | None = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    if tool_call is not None:
        delta["tool_calls"] = [tool_call]
    if content is not None or tool_call is not None:
        delta.setdefault("role", "assistant")
    chunk: dict[str, Any] = {
        "id": "chatcmpl-proxy",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def completion_usage(usage: Any) -> dict[str, Any] | None:
    if not isinstance(usage, dict):
        return None
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def sanitize_responses_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    apply_responses_options(payload, sanitized)
    for key in ("max_tokens", "max_completion_tokens", "response_format", "reasoning_effort", "user"):
        sanitized.pop(key, None)
    return sanitized


def output_items_from_events(state: dict[str, Any]) -> list[dict[str, Any]]:
    items = state.get("output_items")
    if isinstance(items, dict) and items:
        return [items[index] for index in sorted(items)]

    text_parts = state.get("output_text_parts")
    if isinstance(text_parts, dict) and text_parts:
        text = "".join(text_parts[index] for index in sorted(text_parts))
        if text:
            return [
                {
                    "id": f"msg_{uuid.uuid4().hex}",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "annotations": [], "text": text}],
                }
            ]
    return []


def collect_response_output(event: dict[str, Any], state: dict[str, Any]) -> None:
    event_type = event.get("type")
    if event_type == "response.output_text.delta":
        output_index = int(event.get("output_index") or 0)
        delta = event.get("delta")
        if isinstance(delta, str):
            text_parts = state.setdefault("output_text_parts", {})
            text_parts[output_index] = text_parts.get(output_index, "") + delta
        return

    if event_type == "response.output_text.done":
        output_index = int(event.get("output_index") or 0)
        text = event.get("text")
        if isinstance(text, str):
            state.setdefault("output_text_parts", {})[output_index] = text
        return

    if event_type == "response.output_item.done":
        output_index = int(event.get("output_index") or 0)
        item = event.get("item")
        if isinstance(item, dict):
            state.setdefault("output_items", {})[output_index] = item


def event_to_chat_chunks(event: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    event_type = event.get("type")
    model = state.get("model") or ""
    chunks: list[dict[str, Any]] = []

    if event_type == "response.created":
        response = event.get("response")
        if isinstance(response, dict) and isinstance(response.get("model"), str):
            state["model"] = response["model"]
        return []

    if event_type == "response.output_text.delta":
        delta = event.get("delta")
        if isinstance(delta, str) and delta:
            chunks.append(chat_chunk(model=model, content=delta))
        return chunks

    if event_type == "response.output_item.added":
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "function_call":
            item_id = item.get("id") or item.get("call_id") or f"call_{uuid.uuid4().hex}"
            index = len(state.setdefault("tool_order", []))
            state["tool_order"].append(item_id)
            state.setdefault("tool_indexes", {})[item_id] = index
            state.setdefault("tool_calls", {})[item_id] = {
                "id": item.get("call_id") or item_id,
                "type": "function",
                "function": {"name": item.get("name") or "", "arguments": item.get("arguments") or ""},
            }
            chunks.append(
                chat_chunk(
                    model=model,
                    tool_call={
                        "index": index,
                        "id": item.get("call_id") or item_id,
                        "type": "function",
                        "function": {"name": item.get("name") or "", "arguments": item.get("arguments") or ""},
                    },
                )
            )
        return chunks

    if event_type == "response.function_call_arguments.delta":
        item_id = event.get("item_id")
        delta = event.get("delta")
        if isinstance(item_id, str) and isinstance(delta, str):
            indexes = state.setdefault("tool_indexes", {})
            index = indexes.setdefault(item_id, len(indexes))
            tool_calls = state.setdefault("tool_calls", {})
            current = tool_calls.setdefault(
                item_id,
                {"id": item_id, "type": "function", "function": {"name": "", "arguments": ""}},
            )
            current["function"]["arguments"] += delta
            chunks.append(
                chat_chunk(
                    model=model,
                    tool_call={
                        "index": index,
                        "id": current["id"],
                        "type": "function",
                        "function": {"arguments": delta},
                    },
                )
            )
        return chunks

    if event_type == "response.output_item.done":
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "function_call":
            item_id = item.get("id") or item.get("call_id")
            if isinstance(item_id, str):
                indexes = state.setdefault("tool_indexes", {})
                index = indexes.setdefault(item_id, len(indexes))
                tool_calls = state.setdefault("tool_calls", {})
                current = tool_calls.setdefault(
                    item_id,
                    {"id": item.get("call_id") or item_id, "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if item.get("name") and not current["function"].get("name"):
                    current["function"]["name"] = item["name"]
                    chunks.append(
                        chat_chunk(
                            model=model,
                            tool_call={
                                "index": index,
                                "id": current["id"],
                                "type": "function",
                                "function": {"name": item["name"], "arguments": ""},
                            },
                        )
                    )
        return chunks

    if event_type in {"response.completed", "response.failed", "response.incomplete"}:
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        usage = completion_usage(response.get("usage"))
        finish_reason = "tool_calls" if state.get("tool_calls") else "stop"
        if event_type == "response.incomplete":
            finish_reason = "length"
        chunks.append(chat_chunk(model=model, finish_reason=finish_reason, usage=usage))
    return chunks


async def upstream_headers(request: Request) -> dict[str, str]:
    info = await load_auth_info()
    if info.get("mode") == "openai_api_key":
        return {
            "Authorization": f"Bearer {info['api_key']}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "codex-chat-proxy",
        }
    auth = info["auth"]
    tokens = auth["tokens"]
    token = tokens["access_token"]
    claims = decode_jwt(tokens.get("id_token") or token)
    auth_claims = claims.get("https://api.openai.com/auth")
    account = None
    if isinstance(auth_claims, dict):
        value = auth_claims.get("chatgpt_account_id")
        if isinstance(value, str) and value:
            account = value
    if not account and isinstance(tokens.get("account_id"), str):
        account = tokens["account_id"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "OpenAI-Beta": "responses=experimental",
        "originator": "codex_cli_rs",
        "version": codex_client_version(),
        "session_id": request.headers.get("session_id") or str(uuid.uuid4()),
        "conversation_id": request.headers.get("conversation_id") or str(uuid.uuid4()),
        "User-Agent": f"codex_cli_rs/{codex_client_version()}",
    }
    if account:
        headers["chatgpt-account-id"] = account
    return headers


async def send_upstream(payload: dict[str, Any], request: Request) -> httpx.Response:
    info = await load_auth_info()
    base_url = OPENAI_RESPONSES_BASE_URL if info.get("mode") == "openai_api_key" else CODEX_BASE_URL
    upstream_request = http_client.build_request(
        "POST",
        f"{base_url}/responses",
        headers=await upstream_headers(request),
        json=payload,
    )
    return await http_client.send(upstream_request, stream=True)


async def sse_events(response: httpx.Response):
    buffer: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            buffer.append(line[5:].strip())
            continue
        if line == "" and buffer:
            raw = "\n".join(buffer)
            buffer = []
            if raw == "[DONE]":
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if isinstance(payload, dict):
                yield payload
    if buffer:
        try:
            payload = json.loads("\n".join(buffer))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            yield payload


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        info = await load_auth_info()
        auth_mode = info.get("mode", "unavailable")
    except Exception:
        auth_mode = "unavailable"
    return {
        "status": "ok",
        "service": APP_NAME,
        "models": MODEL_IDS,
        "codex_client_version": codex_client_version(),
        "auth_mode": auth_mode,
        "openai_api_key_fallback": auth_mode == "openai_api_key",
        "chat_field_mapping": {
            "tools": "responses.tools",
            "tool_choice": "responses.tool_choice",
            "max_tokens": "responses.max_output_tokens",
            "response_format": "responses.text.format",
            "reasoning_effort": "responses.reasoning.effort",
        },
    }


@app.get("/v1/models")
async def models(request: Request) -> dict[str, Any]:
    require_proxy_key(request)
    return {
        "object": "list",
        "data": [
            {"id": model, "object": "model", "created": 0, "owned_by": "codex-chat-proxy"}
            for model in MODEL_IDS
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    require_proxy_key(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object")
    wants_stream = bool(body.get("stream"))
    model = str(body.get("model") or MODEL_IDS[0])
    response = await send_upstream(chat_to_responses(body), request)
    if response.status_code >= 400:
        content = await response.aread()
        await response.aclose()
        return Response(
            content=content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/json"),
        )

    if wants_stream:
        async def iterator():
            state = {"model": model}
            try:
                async for event in sse_events(response):
                    for chunk in event_to_chat_chunks(event, state):
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                await response.aclose()

        return StreamingResponse(iterator(), media_type="text/event-stream")

    state = {"model": model}
    content_parts: list[str] = []
    tool_calls_by_index: dict[int, dict[str, Any]] = {}
    finish_reason = "stop"
    usage = None
    try:
        async for event in sse_events(response):
            for chunk in event_to_chat_chunks(event, state):
                choice = chunk["choices"][0]
                delta = choice.get("delta") or {}
                if isinstance(delta.get("content"), str):
                    content_parts.append(delta["content"])
                for tool_call in delta.get("tool_calls") or []:
                    index = int(tool_call.get("index") or 0)
                    current = tool_calls_by_index.setdefault(
                        index,
                        {
                            "id": tool_call.get("id") or f"call_{uuid.uuid4().hex}",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    fn = tool_call.get("function") or {}
                    if fn.get("name"):
                        current["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        current["function"]["arguments"] += fn["arguments"]
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                if chunk.get("usage"):
                    usage = chunk["usage"]
    finally:
        await response.aclose()

    message: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
    if tool_calls_by_index:
        message["content"] = None if not message["content"] else message["content"]
        message["tool_calls"] = [tool_calls_by_index[index] for index in sorted(tool_calls_by_index)]
    return JSONResponse(
        {
            "id": "chatcmpl-proxy",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": state.get("model") or model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    )


@app.post("/v1/responses")
async def responses_endpoint(request: Request) -> Response:
    require_proxy_key(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object")

    payload = sanitize_responses_payload(body)
    payload["model"] = payload.get("model") or MODEL_IDS[0]
    payload["instructions"] = payload.get("instructions") or "You are a helpful coding assistant. Follow the user's instructions."
    client_wants_stream = bool(payload.get("stream"))
    payload["stream"] = True
    payload.setdefault("store", False)

    response = await send_upstream(payload, request)
    if response.status_code >= 400:
        content = await response.aread()
        await response.aclose()
        return Response(
            content=content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/json"),
        )

    if client_wants_stream:
        async def iterator():
            try:
                async for event in sse_events(response):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                await response.aclose()

        return StreamingResponse(iterator(), media_type="text/event-stream")

    final_response: dict[str, Any] | None = None
    error_payload: dict[str, Any] | None = None
    output_state: dict[str, Any] = {}
    try:
        async for event in sse_events(response):
            collect_response_output(event, output_state)
            event_type = event.get("type")
            if event_type == "error" and isinstance(event.get("error"), dict):
                error_payload = event["error"]
            if event_type in {"response.completed", "response.failed", "response.incomplete"}:
                response_payload = event.get("response")
                if isinstance(response_payload, dict):
                    final_response = response_payload
    finally:
        await response.aclose()

    if final_response is not None:
        if not final_response.get("output"):
            final_response["output"] = output_items_from_events(output_state)
        return JSONResponse(final_response)
    if error_payload is not None:
        return JSONResponse({"error": error_payload}, status_code=400)
    return JSONResponse({"error": {"message": "No response returned from Codex upstream"}}, status_code=502)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=env("HOST", DEFAULT_BIND),
        port=int(env("PORT", str(DEFAULT_PORT))),
        reload=False,
    )
