from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

from .config import load_config
from .flows import generate_litellm_config_for_port, litellm_env_for_port


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


def run_claude() -> None:
    cfg = load_config()
    os.environ["CLAUDE_PROXY_API_KEY"] = cfg.claude_proxy_api_key
    os.environ["CLAUDE_BIN"] = cfg.claude_bin
    _run_python_service("claude-code-proxy", "CLAUDE_PROXY_API_KEY", cfg.claude_port)


def run_litellm() -> None:
    cfg = load_config()
    port = int(os.environ.get("PORT", str(cfg.litellm_port)))
    config_path_value = os.environ.get("LITELLM_CONFIG", "")
    config_path = Path(config_path_value) if config_path_value else generate_litellm_config_for_port(cfg, port)
    for key, value in litellm_env_for_port(cfg, port).items():
        os.environ[key] = value
    from litellm.proxy.proxy_cli import run_server

    run_server.main(
        args=["--config", str(config_path), "--host", cfg.host, "--port", str(port)],
        standalone_mode=True,
    )


def main(argv: list[str] | None = None) -> None:
    args = list(argv or sys.argv[1:])
    if not args:
        raise SystemExit("Usage: --service <codex|gemini|claude|litellm>")
    service = args[0]
    if service == "codex":
        run_codex()
    elif service == "gemini":
        run_gemini()
    elif service == "claude":
        run_claude()
    elif service == "litellm" or service.startswith("litellm_"):
        run_litellm()
    else:
        raise SystemExit(f"Unknown service: {service}")
