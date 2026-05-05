from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


APP_NAME = "claude-code-proxy"
logging.basicConfig(level=os.environ.get("CLAUDE_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger(APP_NAME)
API_KEY = os.environ.get("CLAUDE_PROXY_API_KEY", "claude-proxy-local-key")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "39123"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "900"))
DEFAULT_MODEL = os.environ.get("CLAUDE_DEFAULT_MODEL", "sonnet")
PERMISSION_MODE = os.environ.get("CLAUDE_PERMISSION_MODE", "bypassPermissions").strip() or "bypassPermissions"
ALLOWED_TOOLS = os.environ.get(
    "CLAUDE_ALLOWED_TOOLS",
    "Task,Bash,BashOutput,KillBash,Read,Edit,Write,MultiEdit,Glob,Grep,LS,TodoWrite,WebSearch,WebFetch,NotebookRead,NotebookEdit,ExitPlanMode",
).strip()
AVAILABLE_TOOLS = os.environ.get("CLAUDE_TOOLS", "default").strip()
DISALLOWED_TOOLS = os.environ.get("CLAUDE_DISALLOWED_TOOLS", "").strip()
MCP_CONFIG = os.environ.get("CLAUDE_MCP_CONFIG", "").strip()
SETTINGS = os.environ.get("CLAUDE_SETTINGS", "").strip()
SETTING_SOURCES = os.environ.get("CLAUDE_SETTING_SOURCES", "").strip()
ADD_DIRS = os.environ.get("CLAUDE_ADD_DIRS", "").strip()
PLUGIN_DIRS = os.environ.get("CLAUDE_PLUGIN_DIRS", "").strip()
SYSTEM_PROMPT = os.environ.get("CLAUDE_SYSTEM_PROMPT", "").strip()
APPEND_SYSTEM_PROMPT = os.environ.get("CLAUDE_APPEND_SYSTEM_PROMPT", "").strip()
BETAS = os.environ.get("CLAUDE_BETAS", "").strip()
FALLBACK_MODEL = os.environ.get("CLAUDE_FALLBACK_MODEL", "").strip()
MAX_BUDGET_USD = os.environ.get("CLAUDE_MAX_BUDGET_USD", "").strip()
EXTRA_ARGS = os.environ.get("CLAUDE_EXTRA_ARGS", "").strip()
MAX_TURNS = os.environ.get("CLAUDE_MAX_TURNS", "8").strip()
AGENT = os.environ.get("CLAUDE_AGENT", "").strip()
AGENTS = os.environ.get("CLAUDE_AGENTS", "").strip()
STRICT_MCP_CONFIG = os.environ.get("CLAUDE_STRICT_MCP_CONFIG", "").strip().lower() in {"1", "true", "yes", "on"}
DANGEROUSLY_SKIP_PERMISSIONS = os.environ.get("CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS", "").strip().lower() in {"1", "true", "yes", "on"}
NO_SESSION_PERSISTENCE = os.environ.get("CLAUDE_NO_SESSION_PERSISTENCE", "1").strip().lower() in {"1", "true", "yes", "on"}
BARE_MODE = os.environ.get("CLAUDE_BARE", "").strip().lower() in {"1", "true", "yes", "on"}
INCLUDE_PARTIAL_MESSAGES = os.environ.get("CLAUDE_INCLUDE_PARTIAL_MESSAGES", "1").strip().lower() in {"1", "true", "yes", "on"}
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
EFFORT_ALIASES = {"minimal": "low"}
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def default_model_catalog() -> list[str]:
    base_models = [
        "claude-code",
        "claude-code-sonnet",
        "claude-code-opus",
        "claude-code-haiku",
        "claude-code-opus-4-7",
        "claude-code-opus-4-6",
        "claude-code-sonnet-4-6",
        "claude-code-haiku-4-5",
        "sonnet",
        "opus",
        "haiku",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    ]
    effort_models: list[str] = []
    effort_matrix = {
        "claude-code-opus": EFFORT_LEVELS,
        "claude-code-opus-4-7": EFFORT_LEVELS,
        "claude-code-opus-4-6": ("low", "medium", "high", "max"),
        "claude-code-sonnet": ("low", "medium", "high", "max"),
        "claude-code-sonnet-4-6": ("low", "medium", "high", "max"),
    }
    for model, efforts in effort_matrix.items():
        effort_models.extend(f"{model}-{effort}" for effort in efforts)
    return list(dict.fromkeys([*base_models, *effort_models]))


MODELS = [
    item.strip()
    for item in os.environ.get(
        "CLAUDE_MODELS", ",".join(default_model_catalog())
    ).split(",")
    if item.strip()
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)


def require_auth(authorization: str | None, x_api_key: str | None) -> None:
    if not API_KEY:
        return
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if x_api_key:
        token = x_api_key
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def now_ms() -> int:
    return int(time.perf_counter() * 1000)


def elapsed_ms(start_ms: int) -> int:
    return now_ms() - start_ms


def truncate_detail(value: str, limit: int = 2000) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + f"... <truncated {len(value) - limit} chars>"


def payload_stats(payload: dict[str, Any]) -> dict[str, int]:
    messages = payload.get("messages", [])
    text_chars = 0
    images = 0
    tool_results = 0
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str):
                text_chars += len(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, str):
                        text_chars += len(block)
                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            text_chars += len(str(block.get("text", "")))
                        elif block.get("type") == "image":
                            images += 1
                        elif block.get("type") == "tool_result":
                            tool_results += 1
    return {"messages": len(messages) if isinstance(messages, list) else 0, "text_chars": text_chars, "images": images, "tool_results": tool_results}


def content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part)
    return str(content or "")


def json_for_prompt(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def image_suffix(media_type: str | None) -> str:
    return IMAGE_EXTENSIONS.get(str(media_type or "").lower(), ".img")


def write_image_block(block: dict[str, Any], directory: str, index: int) -> str | None:
    source = block.get("source")
    if not isinstance(source, dict):
        return None
    if source.get("type") != "base64":
        return None
    data = source.get("data")
    if not isinstance(data, str) or not data:
        return None
    try:
        image_bytes = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return None
    path = Path(directory) / f"image_{index}{image_suffix(source.get('media_type'))}"
    path.write_bytes(image_bytes)
    return str(path)


def split_env_items(value: str, separator: str = ",") -> list[str]:
    return [item.strip() for item in value.split(separator) if item.strip()]


def api_config_to_prompt(payload: dict[str, Any]) -> str:
    config_keys = (
        "max_tokens",
        "tools",
        "tool_choice",
        "thinking",
        "temperature",
        "top_p",
        "top_k",
        "stop_sequences",
        "metadata",
        "service_tier",
        "container",
        "mcp_servers",
        "context_management",
        "output_config",
        "cache_control",
        "inference_geo",
    )
    config = {key: payload[key] for key in config_keys if key in payload}
    if not config:
        return ""
    guidance = [
        "Anthropic Messages API request configuration:",
        json_for_prompt(config),
        "Honor these settings as closely as Claude Code print mode allows.",
        "For Anthropic server tools such as web_search, use Claude Code's built-in WebSearch/WebFetch tools directly when useful.",
        "If custom client tools are provided, return a clear tool request in the response instead of silently ignoring them.",
    ]
    return "\n".join(guidance)


def messages_to_prompt(payload: dict[str, Any], image_dir: str | None = None) -> str:
    chunks: list[str] = []
    image_index = 0
    system = payload.get("system")
    if isinstance(system, str) and system:
        chunks.append(f"System:\n{system}")
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(f"System:\n{block.get('text', '')}")
    api_config = api_config_to_prompt(payload)
    if api_config:
        chunks.append(api_config)
    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = message.get("role", "user")
        content = message.get("content")
        if isinstance(content, str):
            chunks.append(f"{role.title()}:\n{content}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        chunks.append(f"{role.title()}:\n{block.get('text', '')}")
                    elif block.get("type") == "image":
                        image_index += 1
                        image_path = write_image_block(block, image_dir, image_index) if image_dir else None
                        if image_path:
                            chunks.append(f"{role.title()} [image {image_index} file; use Read to inspect]:\n{image_path}")
                        elif isinstance(block.get("source"), dict) and block["source"].get("type") == "url":
                            chunks.append(f"{role.title()} [image {image_index} url]:\n{block['source'].get('url', '')}")
                        elif isinstance(block.get("source"), dict) and block["source"].get("type") == "file":
                            chunks.append(f"{role.title()} [image {image_index} file_id]:\n{block['source'].get('file_id', '')}")
                        else:
                            chunks.append(f"{role.title()} [image {image_index}]:\n{json_for_prompt({k: v for k, v in block.items() if k != 'source'})}")
                    elif block.get("type") == "tool_use":
                        chunks.append(
                            f"{role.title()} [tool_use {block.get('name', '')}]:\n"
                            f"{json.dumps(block.get('input', {}), ensure_ascii=False)}"
                        )
                    elif block.get("type") == "tool_result":
                        result_content = block.get("content", "")
                        chunks.append(
                            f"{role.title()} [tool_result {block.get('tool_use_id', '')}]:\n"
                            f"{content_to_text(result_content)}"
                        )
                    else:
                        chunks.append(
                            f"{role.title()} [{block.get('type', 'content')}]:\n"
                            f"{json_for_prompt(block)}"
                        )
    return "\n\n".join(chunks).strip() or "Reply OK."


def normalize_effort(value: Any) -> str | None:
    effort = str(value or "").strip().lower()
    effort = EFFORT_ALIASES.get(effort, effort)
    if effort in EFFORT_LEVELS:
        return effort
    return None


def split_model_effort(model: str) -> tuple[str, str | None]:
    for effort in EFFORT_LEVELS:
        suffix = f"-{effort}"
        if model.endswith(suffix):
            return model[: -len(suffix)], effort
    return model, None


def normalize_model(model: str | None) -> str:
    model = str(model or "claude-code").strip()
    if not model or model == "claude-code":
        return DEFAULT_MODEL
    if model.startswith("claude-code-"):
        short = model.removeprefix("claude-code-")
        if short.startswith("claude-"):
            return short
        if short.startswith(("opus-", "sonnet-", "haiku-")):
            return f"claude-{short}"
        return short
    if model.startswith(("opus-", "sonnet-", "haiku-")):
        return f"claude-{model}"
    return model


def effort_from_payload(payload: dict[str, Any]) -> str | None:
    candidates: list[Any] = [
        payload.get("effort"),
        payload.get("reasoning_effort"),
    ]
    output_config = payload.get("output_config")
    if isinstance(output_config, dict):
        candidates.append(output_config.get("effort"))
    thinking = payload.get("thinking")
    if isinstance(thinking, dict):
        candidates.append(thinking.get("effort"))
    for candidate in candidates:
        effort = normalize_effort(candidate)
        if effort:
            return effort
    return None


def resolve_model_request(model: str | None, payload: dict[str, Any]) -> tuple[str, str | None]:
    raw_model = str(model or "claude-code").strip()
    model_without_effort, model_effort = split_model_effort(raw_model)
    return normalize_model(model_without_effort), effort_from_payload(payload) or model_effort


def claude_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
    ):
        env.pop(key, None)
    return env


def claude_command(
    prompt: str,
    model: str,
    output_format: str,
    effort: str | None = None,
    max_tokens: int | None = None,
    verbose: bool = False,
) -> list[str]:
    command = [
        CLAUDE_BIN,
        "-p",
        "--model", model,
    ]
    if effort:
        command.extend(["--effort", effort])
    command.extend(["--output-format", output_format])
    if verbose:
        command.append("--verbose")
    if output_format == "stream-json" and INCLUDE_PARTIAL_MESSAGES:
        command.append("--include-partial-messages")
    if BARE_MODE:
        command.append("--bare")
    if NO_SESSION_PERSISTENCE:
        command.append("--no-session-persistence")
    if SETTINGS:
        command.extend(["--settings", SETTINGS])
    if SETTING_SOURCES:
        command.extend(["--setting-sources", SETTING_SOURCES])
    if ADD_DIRS:
        command.extend(["--add-dir", *split_env_items(ADD_DIRS, os.pathsep)])
    for plugin_dir in split_env_items(PLUGIN_DIRS, os.pathsep):
        command.extend(["--plugin-dir", plugin_dir])
    if SYSTEM_PROMPT:
        command.extend(["--system-prompt", SYSTEM_PROMPT])
    if APPEND_SYSTEM_PROMPT:
        command.extend(["--append-system-prompt", APPEND_SYSTEM_PROMPT])
    if BETAS:
        command.extend(["--betas", *split_env_items(BETAS)])
    if MCP_CONFIG:
        command.extend(["--mcp-config", *split_env_items(MCP_CONFIG, os.pathsep)])
    if STRICT_MCP_CONFIG:
        command.append("--strict-mcp-config")
    if FALLBACK_MODEL:
        command.extend(["--fallback-model", FALLBACK_MODEL])
    if MAX_BUDGET_USD:
        command.extend(["--max-budget-usd", MAX_BUDGET_USD])
    if AGENT:
        command.extend(["--agent", AGENT])
    if AGENTS:
        command.extend(["--agents", AGENTS])
    if DANGEROUSLY_SKIP_PERMISSIONS:
        command.append("--dangerously-skip-permissions")
    if PERMISSION_MODE:
        command.extend(["--permission-mode", PERMISSION_MODE])
    if AVAILABLE_TOOLS:
        command.append(f"--tools={AVAILABLE_TOOLS}")
    if ALLOWED_TOOLS:
        command.append(f"--allowed-tools={ALLOWED_TOOLS}")
    if DISALLOWED_TOOLS:
        command.append(f"--disallowed-tools={DISALLOWED_TOOLS}")
    if EXTRA_ARGS:
        command.extend(shlex.split(EXTRA_ARGS))
    if MAX_TURNS:
        command.extend(["--max-turns", MAX_TURNS])
    if prompt:
        command.append(prompt)
    return command


def run_claude_json(
    prompt: str,
    model: str,
    effort: str | None = None,
    max_tokens: int | None = None,
    request_id: str = "-",
) -> dict[str, Any]:
    command = claude_command("", model, "json", effort=effort, max_tokens=max_tokens)
    start_ms = now_ms()
    LOGGER.info("claude_request id=%s phase=cli_start mode=json model=%s effort=%s prompt_chars=%s", request_id, model, effort or "", len(prompt))
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            env=claude_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        LOGGER.warning("claude_request id=%s phase=cli_timeout elapsed_ms=%s timeout=%s", request_id, elapsed_ms(start_ms), CLAUDE_TIMEOUT)
        raise HTTPException(status_code=504, detail=f"claude timed out after {CLAUDE_TIMEOUT}s") from exc
    LOGGER.info(
        "claude_request id=%s phase=cli_done mode=json elapsed_ms=%s returncode=%s stdout_chars=%s stderr_chars=%s",
        request_id,
        elapsed_ms(start_ms),
        completed.returncode,
        len(completed.stdout or ""),
        len(completed.stderr or ""),
    )
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"claude exited with {completed.returncode}"
        )
        LOGGER.warning("claude_request id=%s phase=cli_error detail=%s", request_id, truncate_detail(detail))
        raise HTTPException(status_code=502, detail=detail)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"result": completed.stdout.strip(), "is_text": True}


def run_claude_streaming(prompt: str, model: str, effort: str | None = None, request_id: str = "-") -> subprocess.Popen:
    command = claude_command("", model, "stream-json", effort=effort, verbose=True)
    LOGGER.info("claude_request id=%s phase=cli_start mode=stream model=%s effort=%s prompt_chars=%s", request_id, model, effort or "", len(prompt))
    process = subprocess.Popen(
        command,
        env=claude_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    process.stdin.write(prompt)
    process.stdin.close()
    return process


def parse_claude_json_to_content(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("is_text"):
        return [{"type": "text", "text": result.get("result", "")}]
    content_blocks: list[dict[str, Any]] = []
    raw_result = result.get("result")
    if isinstance(raw_result, str) and raw_result:
        content_blocks.append({"type": "text", "text": raw_result})
    elif isinstance(raw_result, list):
        for block in raw_result:
            if isinstance(block, dict):
                content_blocks.append(block)
    if not content_blocks:
        text = result.get("result") or result.get("text") or ""
        content_blocks.append({"type": "text", "text": str(text)})
    return content_blocks


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": APP_NAME,
        "models": MODELS,
        "effort_levels": EFFORT_LEVELS,
        "default_model": DEFAULT_MODEL,
        "permission_mode": PERMISSION_MODE,
        "allowed_tools": ALLOWED_TOOLS,
        "available_tools": AVAILABLE_TOOLS,
        "disallowed_tools": DISALLOWED_TOOLS,
        "mcp_config": MCP_CONFIG,
        "setting_sources": SETTING_SOURCES,
        "additional_directories": split_env_items(ADD_DIRS, os.pathsep),
        "plugin_directories": split_env_items(PLUGIN_DIRS, os.pathsep),
        "strict_mcp_config": STRICT_MCP_CONFIG,
        "dangerously_skip_permissions": DANGEROUSLY_SKIP_PERMISSIONS,
        "no_session_persistence": NO_SESSION_PERSISTENCE,
        "bare_mode": BARE_MODE,
        "max_turns": MAX_TURNS,
        "claude_bin": CLAUDE_BIN,
    }


@app.get("/v1/models")
async def list_models(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> dict[str, Any]:
    require_auth(authorization, x_api_key)
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": model, "object": "model", "created": now, "owned_by": "claude-code"}
            for model in MODELS
        ],
    }


@app.post("/v1/messages", response_model=None)
async def messages(
    request: Request,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
):
    require_auth(authorization, x_api_key)
    request_id = uuid.uuid4().hex[:12]
    request_start_ms = now_ms()
    payload = await request.json()
    model_raw = payload.get("model") or "claude-code"
    model, effort = resolve_model_request(model_raw, payload)
    max_tokens = payload.get("max_tokens")
    wants_stream = payload.get("stream", False)
    stats = payload_stats(payload)
    LOGGER.info(
        "claude_request id=%s phase=request_start stream=%s model_raw=%s model=%s effort=%s messages=%s images=%s text_chars=%s tool_results=%s",
        request_id,
        bool(wants_stream),
        model_raw,
        model,
        effort or "",
        stats["messages"],
        stats["images"],
        stats["text_chars"],
        stats["tool_results"],
    )

    if wants_stream:
        return await _stream_messages(payload, model, model_raw, effort, max_tokens, request_id, request_start_ms)

    with tempfile.TemporaryDirectory(prefix="claude-proxy-images-") as image_dir:
        prompt_start_ms = now_ms()
        prompt = messages_to_prompt(payload, image_dir)
        LOGGER.info("claude_request id=%s phase=prompt_ready elapsed_ms=%s prompt_chars=%s", request_id, elapsed_ms(prompt_start_ms), len(prompt))
        result = await asyncio.to_thread(run_claude_json, prompt, model, effort, max_tokens, request_id)
    content_blocks = parse_claude_json_to_content(result)
    all_text = " ".join(
        b.get("text", "") for b in content_blocks if b.get("type") == "text"
    )
    stop_reason = "end_turn"
    if any(b.get("type") == "tool_use" for b in content_blocks):
        stop_reason = "tool_use"
    if result.get("stop_reason"):
        stop_reason = result["stop_reason"]

    usage = result.get("usage", {})
    response = {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": model_raw,
        "content": content_blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("input_tokens") or estimate_tokens(prompt),
            "output_tokens": usage.get("output_tokens") or estimate_tokens(all_text),
        },
    }
    LOGGER.info("claude_request id=%s phase=request_done mode=json elapsed_ms=%s stop_reason=%s", request_id, elapsed_ms(request_start_ms), stop_reason)
    return JSONResponse(response)


async def _stream_messages(
    payload: dict[str, Any],
    model: str,
    model_raw: str,
    effort: str | None,
    max_tokens: int | None,
    request_id: str,
    request_start_ms: int,
) -> StreamingResponse:
    msg_id = f"msg_{uuid.uuid4().hex}"
    _ = max_tokens

    async def iterator():
        with tempfile.TemporaryDirectory(prefix="claude-proxy-images-") as image_dir:
            prompt_start_ms = now_ms()
            prompt = messages_to_prompt(payload, image_dir)
            LOGGER.info("claude_request id=%s phase=prompt_ready elapsed_ms=%s prompt_chars=%s", request_id, elapsed_ms(prompt_start_ms), len(prompt))
            event_data = {
                "type": "message_start",
                "message": {
                    "id": msg_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model_raw,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": estimate_tokens(prompt), "output_tokens": 0},
                },
            }
            yield f"event: message_start\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            stream_start_ms = now_ms()
            process = await asyncio.to_thread(run_claude_streaming, prompt, model, effort, request_id)
            block_index = 0
            total_output = 0
            block_open = False
            first_output_logged = False
            saw_stream_content = False
            result_usage: dict[str, Any] = {}
            stop_reason = "end_turn"

            try:
                for raw_line in iter(process.stdout.readline, ""):  # type: ignore[union-attr]
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        event = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type", "")
                    if event_type == "stream_event":
                        inner = event.get("event", {})
                        if isinstance(inner, dict):
                            event = inner
                            event_type = event.get("type", "")

                    if event_type == "content_block_start":
                        if block_open:
                            yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
                            block_index += 1
                        content_block = event.get("content_block") or {"type": "text", "text": ""}
                        yield _sse("content_block_start", {"type": "content_block_start", "index": block_index, "content_block": content_block})
                        block_open = True
                        saw_stream_content = True

                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if isinstance(delta, dict):
                            yield _sse("content_block_delta", {"type": "content_block_delta", "index": event.get("index", block_index), "delta": delta})
                            if delta.get("type") == "text_delta":
                                text_delta = str(delta.get("text", ""))
                                total_output += len(text_delta)
                                if text_delta and not first_output_logged:
                                    first_output_logged = True
                                    LOGGER.info("claude_request id=%s phase=first_output elapsed_ms=%s", request_id, elapsed_ms(stream_start_ms))
                            saw_stream_content = True

                    elif event_type == "content_block_stop":
                        if block_open:
                            yield _sse("content_block_stop", {"type": "content_block_stop", "index": event.get("index", block_index)})
                            block_open = False
                            block_index += 1
                        saw_stream_content = True

                    elif event_type == "message_delta":
                        delta = event.get("delta", {})
                        if isinstance(delta, dict) and delta.get("stop_reason"):
                            stop_reason = delta["stop_reason"]

                    elif event_type == "assistant" and not saw_stream_content:
                        message = event.get("message", {})
                        content_blocks = message.get("content", [])
                        for block in content_blocks:
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type")

                            if btype == "text":
                                text = block.get("text", "")
                                if not text:
                                    continue
                                if block_open:
                                    yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
                                    block_index += 1
                                yield _sse("content_block_start", {"type": "content_block_start", "index": block_index, "content_block": {"type": "text", "text": ""}})
                                block_open = True
                                yield _sse("content_block_delta", {"type": "content_block_delta", "index": block_index, "delta": {"type": "text_delta", "text": text}})
                                if not first_output_logged:
                                    first_output_logged = True
                                    LOGGER.info("claude_request id=%s phase=first_output elapsed_ms=%s", request_id, elapsed_ms(stream_start_ms))
                                total_output += len(text)

                            elif btype == "tool_use":
                                if block_open:
                                    yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
                                    block_index += 1
                                tool_block = {
                                    "type": "tool_use",
                                    "id": block.get("id", f"toolu_{uuid.uuid4().hex}"),
                                    "name": block.get("name", ""),
                                    "input": {},
                                }
                                yield _sse("content_block_start", {"type": "content_block_start", "index": block_index, "content_block": tool_block})
                                block_open = True
                                input_json = json.dumps(block.get("input", {}), ensure_ascii=False)
                                yield _sse("content_block_delta", {"type": "content_block_delta", "index": block_index, "delta": {"type": "input_json_delta", "partial_json": input_json}})
                                stop_reason = "tool_use"

                    elif event_type == "result":
                        usage = event.get("usage", {})
                        result_usage = {
                            "input_tokens": usage.get("input_tokens", 0),
                            "output_tokens": usage.get("output_tokens", 0),
                        }
                        if event.get("stop_reason"):
                            stop_reason = event["stop_reason"]

                process.wait(timeout=10)
                stderr = process.stderr.read() if process.stderr else ""
                LOGGER.info(
                    "claude_request id=%s phase=cli_done mode=stream elapsed_ms=%s returncode=%s stderr_chars=%s",
                    request_id,
                    elapsed_ms(stream_start_ms),
                    process.returncode,
                    len(stderr or ""),
                )
                if process.returncode not in (0, None):
                    LOGGER.warning("claude_request id=%s phase=cli_error detail=%s", request_id, truncate_detail(stderr or f"claude exited with {process.returncode}"))
            except Exception as exc:
                LOGGER.exception("claude_request id=%s phase=stream_exception error=%s", request_id, exc)
                process.kill()
            finally:
                if process.poll() is None:
                    process.kill()

            if block_open:
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
            elif block_index == 0:
                yield _sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})

            out_tokens = result_usage.get("output_tokens") or estimate_tokens("x" * total_output)
            yield _sse("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": out_tokens},
            })
            yield "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"
            LOGGER.info("claude_request id=%s phase=request_done mode=stream elapsed_ms=%s stop_reason=%s", request_id, elapsed_ms(request_start_ms), stop_reason)

    return StreamingResponse(iterator(), media_type="text/event-stream")


def _sse(event_name: str, data: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
