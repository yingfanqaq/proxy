from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import ProxyConfig, load_config, log_dir, runtime_dir
from .flows import generate_litellm_config_for_port, litellm_env_for_port, local_providers_used, output_ports


SOURCE_SERVICES = ("codex", "gemini", "claude")


@dataclass
class ServiceSpec:
    name: str
    port: int
    health_url: str
    log_path: Path
    pid_path: Path
    cwd: Path
    command: list[str]
    env: dict[str, str]


def _root(config: ProxyConfig) -> Path:
    return Path(config.project_root).expanduser().resolve()


def pid_path(name: str) -> Path:
    return runtime_dir() / f"{name}.pid"


def litellm_service_name(port: int) -> str:
    return f"litellm_{port}"


def litellm_port_from_name(name: str, config: ProxyConfig) -> int:
    if name.startswith("litellm_"):
        return int(name.rsplit("_", 1)[1])
    if name == "litellm":
        return config.litellm_port
    raise ValueError(f"Not a LiteLLM service: {name}")


def service_names(config: ProxyConfig | None = None) -> tuple[str, ...]:
    cfg = (config or load_config()).normalized()
    source_names = [name for name in SOURCE_SERVICES if name in local_providers_used(cfg)]
    litellm_names = [litellm_service_name(port) for port in output_ports(cfg)]
    return tuple(source_names + litellm_names)


def log_path(name: str) -> Path:
    if name.startswith("litellm"):
        if name in ("litellm", "litellm_4000"):
            return log_dir() / "litellm-two-proxy.log"
        return log_dir() / f"{name}.log"
    suffix = {
        "codex": "codex-chat-proxy.log",
        "gemini": "gemini-genai-proxy.log",
        "claude": "claude-code-proxy.log",
    }[name]
    return log_dir() / suffix


def generate_litellm_config(config: ProxyConfig) -> Path:
    return generate_litellm_config_for_port(config, config.litellm_port)


def _base_env(config: ProxyConfig) -> dict[str, str]:
    env = os.environ.copy()
    for launchd_key in ("XPC_SERVICE_NAME", "__CFBundleIdentifier", "PYTHONEXECUTABLE"):
        env.pop(launchd_key, None)
    env.update(
        {
            "LOCAL_AI_PROXY_ROOT": config.project_root,
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def _frozen_command(service: str) -> list[str] | None:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--service", service]
    return None


def service_spec(name: str, config: ProxyConfig | None = None) -> ServiceSpec:
    cfg = (config or load_config()).normalized()
    root = _root(cfg)
    env = _base_env(cfg)
    frozen = _frozen_command(name)
    if name == "codex":
        cwd = root / "codex-chat-proxy"
        env.update(
            {
                "CODEX_PROXY_API_KEY": cfg.codex_proxy_api_key,
                "HOST": cfg.host,
                "PORT": str(cfg.codex_port),
                "PYTHON_BIN": cfg.python_bin,
            }
        )
        command = frozen or [cfg.python_bin, "app.py"]
        return ServiceSpec(name, cfg.codex_port, f"http://{cfg.host}:{cfg.codex_port}/health", log_path(name), pid_path(name), cwd, command, env)
    if name == "gemini":
        cwd = root / "gemini-genai-proxy"
        env.update(
            {
                "GEMINI_PROXY_API_KEY": cfg.gemini_proxy_api_key,
                "HOST": cfg.host,
                "PORT": str(cfg.gemini_port),
                "PYTHON_BIN": cfg.python_bin,
            }
        )
        command = frozen or [cfg.python_bin, "app.py"]
        return ServiceSpec(name, cfg.gemini_port, f"http://{cfg.host}:{cfg.gemini_port}/health", log_path(name), pid_path(name), cwd, command, env)
    if name == "claude":
        cwd = root / "claude-code-proxy"
        env.update(
            {
                "CLAUDE_PROXY_API_KEY": cfg.claude_proxy_api_key,
                "CLAUDE_BIN": cfg.claude_bin,
                "HOST": cfg.host,
                "PORT": str(cfg.claude_port),
                "PYTHON_BIN": cfg.python_bin,
            }
        )
        command = frozen or [cfg.python_bin, "app.py"]
        return ServiceSpec(name, cfg.claude_port, f"http://{cfg.host}:{cfg.claude_port}/health", log_path(name), pid_path(name), cwd, command, env)
    if name.startswith("litellm"):
        port = litellm_port_from_name(name, cfg)
        config_path = generate_litellm_config_for_port(cfg, port)
        env.update(litellm_env_for_port(cfg, port))
        env.update({"LITELLM_CONFIG": str(config_path), "HOST": cfg.host, "PORT": str(port)})
        command = frozen or [cfg.litellm_bin, "--config", str(config_path), "--host", cfg.host, "--port", str(port)]
        return ServiceSpec(name, port, f"http://{cfg.host}:{port}/health/readiness", log_path(name), pid_path(name), root, command, env)
    raise ValueError(f"Unknown service: {name}")


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def health_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def status(config: ProxyConfig | None = None) -> dict[str, dict[str, object]]:
    cfg = (config or load_config()).normalized()
    result: dict[str, dict[str, object]] = {}
    for name in service_names(cfg):
        spec = service_spec(name, cfg)
        pid = read_pid(spec.pid_path)
        alive = bool(pid and pid_alive(pid))
        healthy = health_ok(spec.health_url)
        result[name] = {
            "pid": pid,
            "alive": alive,
            "healthy": healthy,
            "port": spec.port,
            "health_url": spec.health_url,
            "log": str(spec.log_path),
            "pid_file": str(spec.pid_path),
        }
    return result


def _mac_launchd_service_path(name: str) -> tuple[str, Path] | None:
    if sys.platform != "darwin":
        return None
    try:
        from . import autostart

        return autostart.mac_service_label(name), autostart.mac_service_plist_path(name)
    except Exception:
        return None


def _wait_for_health(url: str, expected: bool, attempts: int = 40) -> bool:
    for _ in range(attempts):
        if health_ok(url, timeout=0.5) == expected:
            return True
        time.sleep(0.5)
    return False


def start_service(name: str, config: ProxyConfig | None = None) -> dict[str, object]:
    cfg = (config or load_config()).normalized()
    spec = service_spec(name, cfg)
    current = status(cfg)[name]
    if current["healthy"]:
        return {"name": name, "started": False, "reason": "already healthy", **current}
    launchd = _mac_launchd_service_path(name)
    if launchd and launchd[1].exists():
        label, plist_path = launchd
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{label}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        attempts = 100 if name.startswith("litellm") else 40
        healthy = _wait_for_health(spec.health_url, True, attempts=attempts)
        return {"name": name, "started": healthy, "healthy": healthy, "via": "launchd", "log": str(spec.log_path)}
    spec.log_path.parent.mkdir(parents=True, exist_ok=True)
    spec.pid_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = spec.log_path.open("ab")
    creationflags = 0
    popen_kwargs: dict[str, object] = {}
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    process = subprocess.Popen(
        spec.command,
        cwd=str(spec.cwd),
        env=spec.env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        **popen_kwargs,
    )
    spec.pid_path.write_text(str(process.pid), encoding="utf-8")
    for _ in range(30):
        if health_ok(spec.health_url, timeout=0.5):
            return {"name": name, "started": True, "pid": process.pid, "healthy": True, "log": str(spec.log_path)}
        if process.poll() is not None:
            return {"name": name, "started": False, "pid": process.pid, "healthy": False, "exit_code": process.returncode, "log": str(spec.log_path)}
        time.sleep(0.5)
    return {"name": name, "started": True, "pid": process.pid, "healthy": False, "log": str(spec.log_path)}


def start_all(config: ProxyConfig | None = None) -> list[dict[str, object]]:
    cfg = (config or load_config()).normalized()
    results: list[dict[str, object]] = []
    for name in service_names(cfg):
        if not name.startswith("litellm"):
            results.append(start_service(name, cfg))
    for name in service_names(cfg):
        if name.startswith("litellm"):
            results.append(start_service(name, cfg))
    return results


def stop_service(name: str, config: ProxyConfig | None = None) -> dict[str, object]:
    cfg = (config or load_config()).normalized()
    spec = service_spec(name, cfg)
    pid = read_pid(spec.pid_path)
    if not pid or not pid_alive(pid):
        spec.pid_path.unlink(missing_ok=True)
        launchd = _mac_launchd_service_path(name)
        if launchd and launchd[1].exists():
            _label, plist_path = launchd
            domain = f"gui/{os.getuid()}"
            subprocess.run(["launchctl", "bootout", domain, str(plist_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            stopped = _wait_for_health(spec.health_url, False, attempts=20)
            return {"name": name, "stopped": stopped, "via": "launchd"}
        return {"name": name, "stopped": False, "reason": "not running"}
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _ in range(20):
        if not pid_alive(pid):
            break
        time.sleep(0.25)
    if pid_alive(pid) and os.name != "nt":
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    spec.pid_path.unlink(missing_ok=True)
    return {"name": name, "stopped": True, "pid": pid}


def stop_all(config: ProxyConfig | None = None) -> list[dict[str, object]]:
    cfg = (config or load_config()).normalized()
    return [stop_service(name, cfg) for name in reversed(service_names(cfg))]


def restart_all(config: ProxyConfig | None = None) -> list[dict[str, object]]:
    cfg = (config or load_config()).normalized()
    stopped = stop_all(cfg)
    started = start_all(cfg)
    return stopped + started


def print_status(config: ProxyConfig | None = None) -> str:
    return json.dumps(status(config), indent=2, ensure_ascii=False)
