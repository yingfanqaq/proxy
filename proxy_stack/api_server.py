"""REST API server for the Electron frontend — built on FastAPI."""
from __future__ import annotations

from typing import Any

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
    import urllib.request
    import json
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


@app.post("/api/flows/validate")
def validate_flows() -> dict[str, Any]:
    import json
    import urllib.request

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
