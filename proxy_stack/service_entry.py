from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

from .config import load_config
from .manager import generate_litellm_config


def _run_python_service(folder: str, key: str, port: int) -> None:
    cfg = load_config()
    root = Path(cfg.project_root).expanduser().resolve()
    service_dir = root / folder
    os.environ[key] = getattr(cfg, key.lower())
    os.environ["HOST"] = cfg.host
    os.environ["PORT"] = str(port)
    os.chdir(service_dir)
    runpy.run_path(str(service_dir / "app.py"), run_name="__main__")


def run_codex() -> None:
    cfg = load_config()
    os.environ["CODEX_PROXY_API_KEY"] = cfg.codex_proxy_api_key
    _run_python_service("codex-chat-proxy", "CODEX_PROXY_API_KEY", cfg.codex_port)


def run_gemini() -> None:
    cfg = load_config()
    os.environ["GEMINI_PROXY_API_KEY"] = cfg.gemini_proxy_api_key
    _run_python_service("gemini-genai-proxy", "GEMINI_PROXY_API_KEY", cfg.gemini_port)


def run_litellm() -> None:
    cfg = load_config()
    config_path = generate_litellm_config(cfg)
    os.environ["CODEX_PROXY_API_KEY"] = cfg.codex_proxy_api_key
    os.environ["GEMINI_PROXY_API_KEY"] = cfg.gemini_proxy_api_key
    os.environ["LITELLM_MASTER_KEY"] = cfg.litellm_master_key
    from litellm.proxy.proxy_cli import run_server

    run_server.main(
        args=["--config", str(config_path), "--host", cfg.host, "--port", str(cfg.litellm_port)],
        standalone_mode=True,
    )


def main(argv: list[str] | None = None) -> None:
    args = list(argv or sys.argv[1:])
    if not args:
        raise SystemExit("Usage: --service <codex|gemini|litellm>")
    service = args[0]
    if service == "codex":
        run_codex()
    elif service == "gemini":
        run_gemini()
    elif service == "litellm":
        run_litellm()
    else:
        raise SystemExit(f"Unknown service: {service}")
