from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse


APP_NAME = "claude-code-proxy"
API_KEY = os.environ.get("CLAUDE_PROXY_API_KEY", "claude-proxy-local-key")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "39123"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"
CLAUDE_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", "900"))
DEFAULT_MODEL = os.environ.get("CLAUDE_DEFAULT_MODEL", "sonnet")
MODELS = [item.strip() for item in os.environ.get("CLAUDE_MODELS", "claude-code,sonnet,opus,haiku").split(",") if item.strip()]

app = FastAPI(title=APP_NAME)


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
    if system:
        chunks.append(f"System:\n{content_to_text(system)}")
    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = message.get("role", "user")
        text = content_to_text(message.get("content"))
        if text:
            chunks.append(f"{role.title()}:\n{text}")
    return "\n\n".join(chunks).strip() or "Reply OK."


def normalize_model(model: str | None) -> str:
    if not model or model == "claude-code":
        return DEFAULT_MODEL
    if model.startswith("claude-code-"):
        return model.removeprefix("claude-code-")
    return model


def claude_env() -> dict[str, str]:
    env = os.environ.copy()
    # Avoid accidentally routing Claude Code back into this proxy stack.
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


def run_claude(prompt: str, model: str) -> str:
    command = [
        CLAUDE_BIN,
        "-p",
        "--model",
        model,
        "--output-format",
        "text",
        "--permission-mode",
        "dontAsk",
        prompt,
    ]
    completed = subprocess.run(
        command,
        env=claude_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=CLAUDE_TIMEOUT,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"claude exited with {completed.returncode}"
        raise HTTPException(status_code=502, detail=detail)
    return completed.stdout.strip()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": APP_NAME, "models": MODELS, "claude_bin": CLAUDE_BIN}


@app.get("/v1/models")
async def models(authorization: str | None = Header(None), x_api_key: str | None = Header(None)) -> dict[str, Any]:
    require_auth(authorization, x_api_key)
    now = int(time.time())
    return {"object": "list", "data": [{"id": model, "object": "model", "created": now, "owned_by": "claude-code"} for model in MODELS]}


@app.post("/v1/messages")
async def messages(
    request: Request,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> JSONResponse:
    require_auth(authorization, x_api_key)
    payload = await request.json()
    model = normalize_model(payload.get("model"))
    prompt = messages_to_prompt(payload)
    text = await asyncio.to_thread(run_claude, prompt, model)
    response = {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": payload.get("model") or model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    return JSONResponse(response)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
