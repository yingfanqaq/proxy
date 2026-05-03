from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


APP_NAME = "claude-code-proxy"
API_KEY = os.environ.get("CLAUDE_PROXY_API_KEY", "claude-proxy-local-key")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "39123"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "900"))
DEFAULT_MODEL = os.environ.get("CLAUDE_DEFAULT_MODEL", "sonnet")
MODELS = [
    item.strip()
    for item in os.environ.get(
        "CLAUDE_MODELS", "claude-code,sonnet,opus,haiku"
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


def messages_to_prompt(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    system = payload.get("system")
    if isinstance(system, str) and system:
        chunks.append(f"System:\n{system}")
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(f"System:\n{block.get('text', '')}")
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
    return "\n\n".join(chunks).strip() or "Reply OK."


def normalize_model(model: str | None) -> str:
    if not model or model == "claude-code":
        return DEFAULT_MODEL
    if model.startswith("claude-code-"):
        return model.removeprefix("claude-code-")
    return model


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


def run_claude_json(prompt: str, model: str, max_tokens: int | None = None) -> dict[str, Any]:
    command = [
        CLAUDE_BIN,
        "-p",
        "--model", model,
        "--output-format", "json",
        "--permission-mode", "dontAsk",
    ]
    if max_tokens:
        command.extend(["--max-turns", "1"])
    command.append(prompt)
    completed = subprocess.run(
        command,
        env=claude_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=CLAUDE_TIMEOUT,
    )
    if completed.returncode != 0:
        detail = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or f"claude exited with {completed.returncode}"
        )
        raise HTTPException(status_code=502, detail=detail)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"result": completed.stdout.strip(), "is_text": True}


def run_claude_streaming(prompt: str, model: str) -> subprocess.Popen:
    command = [
        CLAUDE_BIN,
        "-p",
        "--model", model,
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", "dontAsk",
        prompt,
    ]
    return subprocess.Popen(
        command,
        env=claude_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


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
    return {"status": "ok", "service": APP_NAME, "models": MODELS, "claude_bin": CLAUDE_BIN}


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
    payload = await request.json()
    model_raw = payload.get("model") or "claude-code"
    model = normalize_model(model_raw)
    prompt = messages_to_prompt(payload)
    max_tokens = payload.get("max_tokens")
    wants_stream = payload.get("stream", False)

    if wants_stream:
        return await _stream_messages(prompt, model, model_raw, max_tokens)

    result = await asyncio.to_thread(run_claude_json, prompt, model, max_tokens)
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
    return JSONResponse(response)


async def _stream_messages(
    prompt: str, model: str, model_raw: str, max_tokens: int | None
) -> StreamingResponse:
    msg_id = f"msg_{uuid.uuid4().hex}"
    _ = max_tokens

    async def iterator():
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

        process = await asyncio.to_thread(run_claude_streaming, prompt, model)
        block_index = 0
        total_output = 0
        block_open = False
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

                if event_type == "assistant":
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
        except Exception:
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

    return StreamingResponse(iterator(), media_type="text/event-stream")


def _sse(event_name: str, data: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
