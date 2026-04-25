from __future__ import annotations

import asyncio
import glob
import json
import os
import platform
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse


APP_NAME = "gemini-genai-proxy"
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 39122
DEFAULT_PROXY_KEY = "gemini-proxy-local-key"
DEFAULT_CODE_ASSIST_BASE_URL = "https://cloudcode-pa.googleapis.com/v1internal"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]
DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

CLIENT_ID_PATTERNS = (
    re.compile(r'\bOAUTH_CLIENT_ID\b\s*=\s*"([^"]+)"'),
    re.compile(r'"client_id"\s*:\s*"([^"]+\.apps\.googleusercontent\.com)"'),
)
CLIENT_SECRET_PATTERNS = (
    re.compile(r'\bOAUTH_CLIENT_SECRET\b\s*=\s*"([^"]+)"'),
    re.compile(r'"client_secret"\s*:\s*"([^"]+)"'),
)


def env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


PROXY_KEY = env("GEMINI_PROXY_API_KEY", DEFAULT_PROXY_KEY)
CODE_ASSIST_BASE_URL = env("CODE_ASSIST_BASE_URL", DEFAULT_CODE_ASSIST_BASE_URL).rstrip("/")
OAUTH_CREDS_PATH = Path(
    env("GEMINI_OAUTH_CREDS_PATH", str(Path.home() / ".gemini" / "oauth_creds.json"))
).expanduser()
ACCOUNTS_PATH = Path(
    env("GEMINI_ACCOUNTS_PATH", str(Path.home() / ".gemini" / "google_accounts.json"))
).expanduser()
TOKEN_URL = env("GEMINI_OAUTH_TOKEN_URL", DEFAULT_TOKEN_URL)
MODEL_IDS = [
    item.strip()
    for item in env("GEMINI_PROXY_MODELS", ",".join(DEFAULT_MODELS)).split(",")
    if item.strip()
]

app = FastAPI(title=APP_NAME)
http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0))
credential_lock = asyncio.Lock()
context_lock = asyncio.Lock()
code_assist_context: dict[str, Any] | None = None


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


def discover_from_file(path: Path, patterns: tuple[re.Pattern[str], ...]) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return None


def installed_gemini_cli_files() -> list[Path]:
    candidates: list[Path] = []
    for pattern in (
        Path.home() / ".nvm" / "versions" / "node" / "*" / "lib" / "node_modules" / "@google" / "gemini-cli" / "bundle" / "*.js",
        Path("/opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/*.js"),
        Path("/usr/local/lib/node_modules/@google/gemini-cli/bundle/*.js"),
    ):
        candidates.extend(Path(item) for item in glob.glob(str(pattern)))
    return [path for path in candidates if path.is_file()]


def discover_oauth_value(
    env_name: str,
    patterns: tuple[re.Pattern[str], ...],
) -> str | None:
    value = os.environ.get(env_name)
    if value:
        return value
    for path in installed_gemini_cli_files():
        value = discover_from_file(path, patterns)
        if value:
            return value
    return None


def is_expiring(credentials: dict[str, Any]) -> bool:
    expiry_date = credentials.get("expiry_date")
    if not isinstance(expiry_date, int):
        return False
    return expiry_date <= int((time.time() + 120) * 1000)


async def active_account() -> str | None:
    if not ACCOUNTS_PATH.exists():
        return None
    try:
        payload = await asyncio.to_thread(read_json, ACCOUNTS_PATH)
    except Exception:
        return None
    active = payload.get("active")
    return active if isinstance(active, str) and active else None


async def load_credentials() -> dict[str, Any]:
    if not OAUTH_CREDS_PATH.exists():
        raise HTTPException(status_code=401, detail=f"Gemini OAuth file not found: {OAUTH_CREDS_PATH}")
    credentials = await asyncio.to_thread(read_json, OAUTH_CREDS_PATH)
    if not credentials.get("access_token"):
        raise HTTPException(status_code=401, detail="Gemini OAuth credentials have no access_token")
    if not is_expiring(credentials):
        return credentials
    return await refresh_credentials(credentials)


async def refresh_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
    async with credential_lock:
        current = await asyncio.to_thread(read_json, OAUTH_CREDS_PATH)
        if not is_expiring(current):
            return current

        refresh_token = current.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            return current

        client_id = discover_oauth_value("GEMINI_OAUTH_CLIENT_ID", CLIENT_ID_PATTERNS)
        client_secret = discover_oauth_value("GEMINI_OAUTH_CLIENT_SECRET", CLIENT_SECRET_PATTERNS)
        if not client_id:
            return current

        form_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "scope": " ".join(DEFAULT_SCOPES),
        }
        if client_secret:
            form_data["client_secret"] = client_secret

        response = await http_client.post(
            TOKEN_URL,
            data=form_data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        response.raise_for_status()
        payload = response.json()
        expires_in = payload.get("expires_in")
        expiry_date = (
            int((time.time() + float(expires_in)) * 1000)
            if isinstance(expires_in, (int, float))
            else current.get("expiry_date")
        )
        updated = {
            **current,
            "access_token": payload.get("access_token") or current.get("access_token"),
            "refresh_token": payload.get("refresh_token") or refresh_token,
            "id_token": payload.get("id_token") or current.get("id_token"),
            "token_type": payload.get("token_type") or current.get("token_type") or "Bearer",
            "scope": payload.get("scope") or current.get("scope"),
            "expiry_date": expiry_date,
            "account_email": current.get("account_email") or await active_account(),
        }
        await asyncio.to_thread(write_json, OAUTH_CREDS_PATH, updated)
        return updated


async def access_token() -> str:
    credentials = await load_credentials()
    token = credentials.get("access_token")
    if not isinstance(token, str) or not token:
        raise HTTPException(status_code=401, detail="Gemini OAuth token unavailable")
    return token


def require_proxy_key(request: Request) -> None:
    candidates = [
        request.query_params.get("key"),
        request.headers.get("x-goog-api-key"),
    ]
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        candidates.append(auth_header.split(None, 1)[1].strip())
    if PROXY_KEY and PROXY_KEY not in candidates:
        raise HTTPException(status_code=401, detail="Invalid GEMINI_API_KEY for proxy")


def base_origin() -> str:
    parsed = urlparse(CODE_ASSIST_BASE_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


def client_metadata() -> dict[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        platform_name = "DARWIN_ARM64"
    elif system == "darwin":
        platform_name = "DARWIN_AMD64"
    elif system == "linux" and machine in {"arm64", "aarch64"}:
        platform_name = "LINUX_ARM64"
    elif system == "linux":
        platform_name = "LINUX_AMD64"
    elif system == "windows":
        platform_name = "WINDOWS_AMD64"
    else:
        platform_name = "PLATFORM_UNSPECIFIED"
    return {"ideName": "IDE_UNSPECIFIED", "pluginType": "GEMINI", "platform": platform_name}


async def load_code_assist_context(force: bool = False) -> dict[str, Any]:
    global code_assist_context
    async with context_lock:
        if code_assist_context is not None and not force:
            return dict(code_assist_context)
        token = await access_token()
        response = await http_client.post(
            f"{CODE_ASSIST_BASE_URL}:loadCodeAssist",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"metadata": client_metadata()},
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.text[:1000])
        payload = response.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="Invalid Code Assist context")
        code_assist_context = payload
        return dict(payload)


async def project_id() -> str | None:
    context = await load_code_assist_context()
    project = context.get("cloudaicompanionProject")
    return project if isinstance(project, str) and project else None


def normalize_model_name(model_name: str) -> str:
    model_name = model_name.strip("/")
    if model_name.startswith("models/"):
        return model_name.split("/", 1)[1]
    return model_name


def make_code_assist_request(model_name: str, body: dict[str, Any], project: str | None) -> dict[str, Any]:
    request_body = dict(body)
    request_body.pop("cachedContent", None)
    payload: dict[str, Any] = {
        "model": normalize_model_name(model_name),
        "user_prompt_id": f"gemini-proxy-{uuid.uuid4().hex}",
        "request": request_body,
    }
    if project:
        payload["project"] = project
    return payload


def unwrap_code_assist(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
        return payload["response"]
    return payload


def parse_sse_payloads() -> tuple[list[str], str | None]:
    return [], None


async def upstream_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {await access_token()}",
        "Content-Type": "application/json",
    }


async def post_code_assist(operation: str, payload: dict[str, Any]) -> Response:
    response = await http_client.post(
        f"{CODE_ASSIST_BASE_URL}:{operation}",
        headers=await upstream_headers(),
        json=payload,
    )
    content_type = response.headers.get("content-type", "application/json")
    if response.status_code >= 400:
        return Response(content=response.content, status_code=response.status_code, media_type=content_type)
    try:
        unwrapped = unwrap_code_assist(response.json())
    except Exception:
        return Response(content=response.content, status_code=response.status_code, media_type=content_type)
    return JSONResponse(unwrapped, status_code=response.status_code)


async def stream_code_assist(payload: dict[str, Any]) -> Response:
    request = http_client.build_request(
        "POST",
        f"{CODE_ASSIST_BASE_URL}:streamGenerateContent?alt=sse",
        headers=await upstream_headers(),
        json=payload,
    )
    response = await http_client.send(request, stream=True)
    if response.status_code >= 400:
        content = await response.aread()
        await response.aclose()
        return Response(
            content=content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/json"),
        )

    async def iterator():
        buffer: list[str] = []
        try:
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    buffer.append(line[5:].strip())
                    continue
                if line == "" and buffer:
                    raw_payload = "\n".join(buffer)
                    buffer = []
                    if raw_payload == "[DONE]":
                        continue
                    try:
                        parsed = json.loads(raw_payload)
                    except Exception:
                        continue
                    yield f"data: {json.dumps(unwrap_code_assist(parsed), ensure_ascii=False)}\n\n"
            if buffer:
                try:
                    parsed = json.loads("\n".join(buffer))
                    yield f"data: {json.dumps(unwrap_code_assist(parsed), ensure_ascii=False)}\n\n"
                except Exception:
                    pass
        finally:
            await response.aclose()

    return StreamingResponse(iterator(), media_type="text/event-stream")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": APP_NAME, "models": MODEL_IDS}


@app.get("/v1beta/models")
@app.get("/v1/models")
async def models(request: Request) -> dict[str, Any]:
    require_proxy_key(request)
    return {
        "models": [
            {
                "name": f"models/{model}",
                "version": model,
                "displayName": model,
                "supportedGenerationMethods": ["generateContent", "streamGenerateContent", "countTokens"],
            }
            for model in MODEL_IDS
        ]
    }


@app.post("/v1beta/models/{model_name:path}:generateContent")
@app.post("/v1/models/{model_name:path}:generateContent")
async def generate_content(model_name: str, request: Request) -> Response:
    require_proxy_key(request)
    body = await request.json()
    project = await project_id()
    return await post_code_assist("generateContent", make_code_assist_request(model_name, body, project))


@app.post("/v1beta/models/{model_name:path}:streamGenerateContent")
@app.post("/v1/models/{model_name:path}:streamGenerateContent")
async def stream_generate_content(model_name: str, request: Request) -> Response:
    require_proxy_key(request)
    body = await request.json()
    project = await project_id()
    return await stream_code_assist(make_code_assist_request(model_name, body, project))


@app.post("/v1beta/models/{model_name:path}:countTokens")
@app.post("/v1/models/{model_name:path}:countTokens")
async def count_tokens(model_name: str, request: Request) -> Response:
    require_proxy_key(request)
    body = await request.json()
    count_payload = {
        "request": {
            "model": f"models/{normalize_model_name(model_name)}",
            "contents": body.get("contents", []),
        }
    }
    if isinstance(body.get("systemInstruction"), dict):
        count_payload["request"]["systemInstruction"] = body["systemInstruction"]
    return await post_code_assist("countTokens", count_payload)


@app.on_event("shutdown")
async def shutdown() -> None:
    await http_client.aclose()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=env("HOST", DEFAULT_BIND),
        port=int(env("PORT", str(DEFAULT_PORT))),
        reload=False,
    )
