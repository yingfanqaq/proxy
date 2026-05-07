"""REST API server for the Electron frontend — built on FastAPI."""
from __future__ import annotations

from typing import Any
from urllib.error import HTTPError, URLError
import json
import urllib.request

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import load_config, save_config
from .flows import flow_summary, normalized_flows
from .manager import restart_all, start_all, status, stop_all

app = FastAPI(title="proxyEverywhere API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _normalize_api_base(base_url: Any) -> str:
    return str(base_url or "").strip().rstrip("/")


def _join_api_url(base_url: str, path: str) -> str:
    return f"{base_url}/{path.lstrip('/')}"


def _api_headers(api_key: str, provider: str, json_body: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if json_body:
        headers["Content-Type"] = "application/json"
    if not api_key:
        return headers
    if provider == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "gemini":
        headers["x-goog-api-key"] = api_key
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _request_json(url: str, headers: dict[str, str], body: dict[str, Any] | None = None, timeout: int = 12) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = raw
        return resp.status, parsed


def _error_detail(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        try:
            body = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            body = ""
        return f"HTTP {exc.code}{': ' + body if body else ''}"
    if isinstance(exc, URLError):
        return str(exc.reason)
    return str(exc)


def test_external_api_source(data: dict[str, Any]) -> dict[str, Any]:
    provider = str(data.get("provider") or data.get("format") or "openai").lower()
    if provider == "claude-api":
        provider = "anthropic"
    protocol = str(data.get("protocol") or "").lower()
    if "anthropic" in protocol or "claude" in protocol:
        provider = "anthropic"
    elif "gemini" in protocol:
        provider = "gemini"
    base_url = _normalize_api_base(data.get("baseUrl") or data.get("base_url"))
    api_key = str(data.get("apiKey") or data.get("api_key") or "")
    if not base_url:
        return {"ok": False, "detail": "Base URL is required."}
    attempts: list[dict[str, Any]] = []

    def attempt(label: str, path: str, body: dict[str, Any] | None = None) -> tuple[bool, Any]:
        url = _join_api_url(base_url, path)
        try:
            status_code, payload = _request_json(url, _api_headers(api_key, provider, body is not None), body)
            attempts.append({"label": label, "url": url, "ok": 200 <= status_code < 300, "status": status_code})
            return 200 <= status_code < 300, payload
        except Exception as exc:
            attempts.append({"label": label, "url": url, "ok": False, "detail": _error_detail(exc)})
            return False, None

    if provider == "gemini":
        ok, payload = attempt("list_models", "/v1beta/models")
        return {"ok": ok, "detail": "Gemini model list is reachable." if ok else "Gemini model list failed.", "models": [item.get("name", "").split("/")[-1] for item in (payload or {}).get("models", []) if isinstance(item, dict)], "attempts": attempts}

    if provider == "anthropic":
        ok, payload = attempt("list_models", "/v1/models")
        models = [item.get("id") for item in (payload or {}).get("data", []) if isinstance(item, dict) and item.get("id")] if isinstance(payload, dict) else []
        if ok:
            return {"ok": True, "detail": "Anthropic model list is reachable.", "models": models, "attempts": attempts}
        configured_model = str(data.get("model") or "").strip()
        candidate_models = [
            configured_model,
            "claude-sonnet-4-6",
            "claude-opus-4-7",
            "claude-opus-4-6",
            "claude-haiku-4-5",
            "sonnet",
            "opus",
            "haiku",
            "claude-code-sonnet",
            "claude-code-opus",
            "claude-code-haiku",
        ]
        seen_models: set[str] = set()
        for model in candidate_models:
            if not model or model in seen_models:
                continue
            seen_models.add(model)
            body = {"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]}
            ok, _payload = attempt(f"messages:{model}", "/v1/messages", body)
            if ok:
                return {"ok": True, "detail": f"Anthropic messages endpoint is reachable with model {model}.", "models": models or list(seen_models), "attempts": attempts}
        return {"ok": False, "detail": "Anthropic model list and messages checks failed.", "models": models, "attempts": attempts}

    ok, payload = attempt("list_models", "/v1/models")
    models = [item.get("id") for item in (payload or {}).get("data", []) if isinstance(item, dict) and item.get("id")] if isinstance(payload, dict) else []
    if ok:
        return {"ok": True, "detail": "OpenAI-compatible model list is reachable.", "models": models, "attempts": attempts}
    body = {"model": str(data.get("model") or "test"), "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}
    ok, _payload = attempt("chat_completions", "/v1/chat/completions", body)
    return {"ok": ok, "detail": "OpenAI-compatible chat endpoint is reachable." if ok else "OpenAI-compatible model list and chat checks failed.", "models": models, "attempts": attempts}


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    return status()


@app.get("/api/flows")
def get_flows() -> list[dict[str, Any]]:
    cfg = load_config()
    return normalized_flows(cfg.flows)


@app.put("/api/flows")
def put_flows(flows: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = load_config()
    cfg.flows = flows
    save_config(cfg)
    return {"ok": True, "count": len(flows)}


@app.get("/api/flows/summary")
def get_flow_summary() -> list[dict[str, Any]]:
    return flow_summary(load_config())


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    cfg = load_config()
    return {
        "host": cfg.host,
        "codex_port": cfg.codex_port,
        "gemini_port": cfg.gemini_port,
        "claude_port": cfg.claude_port,
        "litellm_port": cfg.litellm_port,
        "settings_port": cfg.settings_port,
        "codex_proxy_api_key": cfg.codex_proxy_api_key,
        "gemini_proxy_api_key": cfg.gemini_proxy_api_key,
        "claude_proxy_api_key": cfg.claude_proxy_api_key,
        "litellm_master_key": cfg.litellm_master_key,
    }


@app.put("/api/config")
def put_config(data: dict[str, Any]) -> dict[str, Any]:
    from .config import update_config
    cfg = update_config(data)
    return {"ok": True}


@app.get("/api/proxy-models/{provider}")
def get_proxy_models(provider: str) -> dict[str, Any]:
    cfg = load_config()
    ports = {"codex": cfg.codex_port, "gemini": cfg.gemini_port, "claude": cfg.claude_port}
    keys = {"codex": cfg.codex_proxy_api_key, "gemini": cfg.gemini_proxy_api_key, "claude": cfg.claude_proxy_api_key}
    port = ports.get(provider)
    key = keys.get(provider, "")
    if not port:
        return {"provider": provider, "models": [], "error": "unknown provider"}
    try:
        if provider == "gemini":
            url = f"http://{cfg.host}:{port}/v1beta/models"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = [m["name"].split("/")[-1] for m in data.get("models", [])]
        else:
            url = f"http://{cfg.host}:{port}/v1/models"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = [m["id"] for m in data.get("data", [])]
        return {"provider": provider, "models": models}
    except Exception as exc:
        return {"provider": provider, "models": [], "error": str(exc)}


@app.post("/api/external-api/test")
def test_external_api(data: dict[str, Any]) -> dict[str, Any]:
    return test_external_api_source(data)


@app.post("/api/flows/validate")
def validate_flows() -> dict[str, Any]:
    from .flows import enabled_flows_for_port, output_api_key, output_ports

    cfg = load_config()
    current = status(cfg)
    checks: list[dict[str, Any]] = []

    for name, info in current.items():
        checks.append(
            {
                "kind": "service",
                "name": name,
                "ok": bool(info.get("healthy")),
                "port": info.get("port"),
                "detail": "healthy" if info.get("healthy") else f"health check failed: {info.get('health_url')}",
            }
        )

    for port in output_ports(cfg):
        flows = enabled_flows_for_port(cfg, port)
        expected_models = {
            str(model.get("name"))
            for flow in flows
            for model in flow.get("models", [])
            if model.get("name")
        }
        url = f"http://{cfg.host}:{port}/v1/models"
        key = output_api_key(cfg, port)
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read())
            returned_models = {
                str(item.get("id"))
                for item in data.get("data", [])
                if isinstance(item, dict) and item.get("id")
            }
            missing = sorted(expected_models - returned_models)
            checks.append(
                {
                    "kind": "output",
                    "name": f"litellm_{port}",
                    "ok": not missing,
                    "port": port,
                    "detail": f"{len(returned_models)} model(s) listed" if not missing else f"missing model route(s): {', '.join(missing[:8])}",
                    "expected_models": sorted(expected_models),
                    "returned_models": sorted(returned_models),
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "kind": "output",
                    "name": f"litellm_{port}",
                    "ok": False,
                    "port": port,
                    "detail": f"model list request failed: {exc}",
                    "expected_models": sorted(expected_models),
                    "returned_models": [],
                }
            )

    return {"ok": all(bool(item.get("ok")) for item in checks), "checks": checks}


@app.post("/api/services/start")
def do_start() -> dict[str, Any]:
    try:
        result = start_all()
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/services/stop")
def do_stop() -> dict[str, Any]:
    try:
        result = stop_all()
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/services/restart")
def do_restart() -> dict[str, Any]:
    try:
        result = restart_all()
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/flows/save-and-restart")
def save_and_restart(flows: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = load_config()
    cfg.flows = flows
    save_config(cfg)
    try:
        result = restart_all()
        return {"ok": True, "count": len(flows), "result": result}
    except Exception as exc:
        return {"ok": False, "count": len(flows), "error": str(exc)}


def run_api_server(host: str = "127.0.0.1", port: int = 39201) -> None:
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")
