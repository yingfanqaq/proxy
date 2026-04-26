from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from . import APP_ID


def platform_name() -> str:
    return platform.system().lower()


def user_config_dir() -> Path:
    system = platform_name()
    home = Path.home()
    if system == "darwin":
        return home / "Library" / "Application Support" / "LocalAIProxyStack"
    if system == "windows":
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "LocalAIProxyStack"
    return Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "local-ai-proxy-stack"


def user_state_dir() -> Path:
    system = platform_name()
    home = Path.home()
    if system == "darwin":
        return home / "Library" / "Application Support" / "LocalAIProxyStack"
    if system == "windows":
        return Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "LocalAIProxyStack"
    return Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state")) / "local-ai-proxy-stack"


def bundled_root() -> Path:
    explicit = os.environ.get("LOCAL_AI_PROXY_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    return Path(__file__).resolve().parents[1]


def default_python_bin() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return sys.executable or shutil.which("python3") or shutil.which("python") or "python3"


def default_litellm_bin() -> str:
    found = shutil.which("litellm")
    if found:
        return found
    home_candidate = Path.home() / ".local" / "bin" / ("litellm.exe" if platform_name() == "windows" else "litellm")
    if home_candidate.exists():
        return str(home_candidate)
    return "litellm"


@dataclass
class ProxyConfig:
    host: str = "127.0.0.1"
    codex_port: int = 39121
    gemini_port: int = 39122
    litellm_port: int = 4000
    settings_port: int = 39200
    codex_proxy_api_key: str = "codex-proxy-local-key"
    gemini_proxy_api_key: str = "gemini-proxy-local-key"
    litellm_master_key: str = "litellm-local-test-key"
    python_bin: str = ""
    litellm_bin: str = ""
    project_root: str = ""
    start_services_on_app_launch: bool = True
    open_settings_on_start: bool = False

    def normalized(self) -> "ProxyConfig":
        if not self.python_bin:
            self.python_bin = default_python_bin()
        if not self.litellm_bin:
            self.litellm_bin = default_litellm_bin()
        if not self.project_root:
            self.project_root = str(bundled_root())
        return self

    @property
    def openai_base_url(self) -> str:
        return f"http://{self.host}:{self.codex_port}/v1"

    @property
    def gemini_base_url(self) -> str:
        return f"http://{self.host}:{self.gemini_port}"

    @property
    def anthropic_base_url(self) -> str:
        return f"http://{self.host}:{self.litellm_port}"

    @property
    def settings_url(self) -> str:
        return f"http://{self.host}:{self.settings_port}"


def config_path() -> Path:
    return user_config_dir() / "config.json"


def state_dir() -> Path:
    return user_state_dir()


def runtime_dir() -> Path:
    return state_dir() / "runtime"


def log_dir() -> Path:
    return state_dir() / "logs"


def ensure_dirs() -> None:
    user_config_dir().mkdir(parents=True, exist_ok=True)
    runtime_dir().mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)


def load_config() -> ProxyConfig:
    ensure_dirs()
    path = config_path()
    if not path.exists():
        cfg = ProxyConfig().normalized()
        save_config(cfg)
        return cfg
    data = json.loads(path.read_text(encoding="utf-8"))
    allowed = {field.name for field in fields(ProxyConfig)}
    cfg = ProxyConfig(**{key: value for key, value in data.items() if key in allowed}).normalized()
    return cfg


def save_config(config: ProxyConfig) -> None:
    ensure_dirs()
    config.normalized()
    config_path().write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def update_config(values: dict[str, Any]) -> ProxyConfig:
    cfg = load_config()
    for field in fields(ProxyConfig):
        if field.name not in values:
            continue
        value = values[field.name]
        if field.type is int:
            value = int(value)
        if field.type is bool:
            value = bool(value)
        setattr(cfg, field.name, value)
    save_config(cfg)
    return cfg


def env_snippets(config: ProxyConfig | None = None) -> dict[str, str]:
    cfg = (config or load_config()).normalized()
    return {
        "openai": "\n".join(
            [
                f"export OPENAI_BASE_URL={cfg.openai_base_url}",
                f"export OPENAI_API_KEY={cfg.codex_proxy_api_key}",
            ]
        ),
        "gemini": "\n".join(
            [
                f"export GOOGLE_GEMINI_BASE_URL={cfg.gemini_base_url}",
                f"export GEMINI_API_KEY={cfg.gemini_proxy_api_key}",
            ]
        ),
        "anthropic_codex": "\n".join(
            [
                "unset ANTHROPIC_AUTH_TOKEN",
                f"export ANTHROPIC_BASE_URL={cfg.anthropic_base_url}",
                f"export ANTHROPIC_API_KEY={cfg.litellm_master_key}",
                "export ANTHROPIC_MODEL=gpt-5.5",
                "export ANTHROPIC_DEFAULT_HAIKU_MODEL=gpt-5.4-mini",
                "export ANTHROPIC_DEFAULT_SONNET_MODEL=gpt-5.4",
                "export ANTHROPIC_DEFAULT_OPUS_MODEL=gpt-5.5",
            ]
        ),
        "anthropic_gemini": "\n".join(
            [
                "unset ANTHROPIC_AUTH_TOKEN",
                f"export ANTHROPIC_BASE_URL={cfg.anthropic_base_url}",
                f"export ANTHROPIC_API_KEY={cfg.litellm_master_key}",
                "export ANTHROPIC_MODEL=gemini-3.1-pro-preview",
                "export ANTHROPIC_DEFAULT_HAIKU_MODEL=gemini-3.1-flash-lite-preview",
                "export ANTHROPIC_DEFAULT_SONNET_MODEL=gemini-3-flash",
                "export ANTHROPIC_DEFAULT_OPUS_MODEL=gemini-3.1-pro-preview",
            ]
        ),
    }


def app_environment(config: ProxyConfig | None = None) -> dict[str, str]:
    cfg = (config or load_config()).normalized()
    return {
        "LOCAL_AI_PROXY_ROOT": cfg.project_root,
        "LOCAL_AI_PROXY_CONFIG": str(config_path()),
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(Path.home()),
    }
