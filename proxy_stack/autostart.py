from __future__ import annotations

import os
import plistlib
import platform
import shlex
import subprocess
import sys
from pathlib import Path

from . import APP_ID, APP_NAME
from .config import app_environment, load_config, log_dir


LEGACY_MAC_LABELS = (
    "com.yingfanqaq.codex-chat-proxy",
    "com.yingfanqaq.gemini-genai-proxy",
    "com.yingfanqaq.litellm-two-proxy",
)

MAC_SERVICE_LABELS = {
    "codex": f"{APP_ID}.codex",
    "gemini": f"{APP_ID}.gemini",
    "litellm": f"{APP_ID}.litellm",
}


def launch_command(start_services: bool = True) -> list[str]:
    command = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "proxy_stack.tray_app"]
    if start_services:
        command.append("--start-services")
    return command


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"


def mac_service_plist_path(name: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_SERVICE_LABELS[name]}.plist"


def mac_service_label(name: str) -> str:
    return MAC_SERVICE_LABELS[name]


def _linux_desktop_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / f"{APP_ID}.desktop"


def _windows_command() -> str:
    return subprocess.list2cmdline(launch_command())


def remove_legacy_macos_agents() -> None:
    if platform.system() != "Darwin":
        return
    domain = f"gui/{os.getuid()}"
    agent_dir = Path.home() / "Library" / "LaunchAgents"
    for label in LEGACY_MAC_LABELS:
        plist_path = agent_dir / f"{label}.plist"
        subprocess.run(["launchctl", "bootout", domain, str(plist_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        plist_path.unlink(missing_ok=True)


def _mac_common_env(cfg) -> dict[str, str]:
    return {
        **app_environment(cfg),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
    }


def _write_macos_plist(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)


def _bootstrap_macos_plist(path: Path, label: str) -> None:
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    subprocess.run(["launchctl", "enable", f"{domain}/{label}"], check=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{label}"], check=True)


def _mac_service_payloads(cfg) -> dict[str, tuple[Path, dict]]:
    from .manager import generate_litellm_config

    logs = log_dir()
    common_env = _mac_common_env(cfg)
    litellm_config = generate_litellm_config(cfg)
    root = Path(cfg.project_root)
    codex_command = [sys.executable, "--service", "codex"] if getattr(sys, "frozen", False) else [cfg.python_bin, "app.py"]
    gemini_command = [sys.executable, "--service", "gemini"] if getattr(sys, "frozen", False) else [cfg.python_bin, "app.py"]
    litellm_command = [sys.executable, "--service", "litellm"] if getattr(sys, "frozen", False) else [cfg.litellm_bin, "--config", str(litellm_config), "--host", cfg.host, "--port", str(cfg.litellm_port)]
    codex_cwd = cfg.project_root if getattr(sys, "frozen", False) else str(root / "codex-chat-proxy")
    gemini_cwd = cfg.project_root if getattr(sys, "frozen", False) else str(root / "gemini-genai-proxy")
    return {
        "codex": (
            mac_service_plist_path("codex"),
            {
                "Label": MAC_SERVICE_LABELS["codex"],
                "ProgramArguments": codex_command,
                "WorkingDirectory": codex_cwd,
                "EnvironmentVariables": {**common_env, "CODEX_PROXY_API_KEY": cfg.codex_proxy_api_key, "HOST": cfg.host, "PORT": str(cfg.codex_port), "PYTHONUNBUFFERED": "1"},
                "RunAtLoad": True,
                "KeepAlive": True,
                "StandardOutPath": str(logs / "codex-chat-proxy.log"),
                "StandardErrorPath": str(logs / "codex-chat-proxy.log"),
            },
        ),
        "gemini": (
            mac_service_plist_path("gemini"),
            {
                "Label": MAC_SERVICE_LABELS["gemini"],
                "ProgramArguments": gemini_command,
                "WorkingDirectory": gemini_cwd,
                "EnvironmentVariables": {**common_env, "GEMINI_PROXY_API_KEY": cfg.gemini_proxy_api_key, "HOST": cfg.host, "PORT": str(cfg.gemini_port), "PYTHONUNBUFFERED": "1"},
                "RunAtLoad": True,
                "KeepAlive": True,
                "StandardOutPath": str(logs / "gemini-genai-proxy.log"),
                "StandardErrorPath": str(logs / "gemini-genai-proxy.log"),
            },
        ),
        "litellm": (
            mac_service_plist_path("litellm"),
            {
                "Label": MAC_SERVICE_LABELS["litellm"],
                "ProgramArguments": litellm_command,
                "WorkingDirectory": cfg.project_root,
                "EnvironmentVariables": {**common_env, "CODEX_PROXY_API_KEY": cfg.codex_proxy_api_key, "GEMINI_PROXY_API_KEY": cfg.gemini_proxy_api_key, "LITELLM_MASTER_KEY": cfg.litellm_master_key, "PYTHONUNBUFFERED": "1"},
                "RunAtLoad": True,
                "KeepAlive": True,
                "StandardOutPath": str(logs / "litellm-two-proxy.log"),
                "StandardErrorPath": str(logs / "litellm-two-proxy.log"),
            },
        ),
    }


def install_macos() -> Path:
    remove_legacy_macos_agents()
    cfg = load_config()
    for _name, (service_path, service_payload) in _mac_service_payloads(cfg).items():
        _write_macos_plist(service_path, service_payload)
        _bootstrap_macos_plist(service_path, service_payload["Label"])

    plist_path = _mac_plist_path()
    payload = {
        "Label": APP_ID,
        "ProgramArguments": launch_command(start_services=False),
        "WorkingDirectory": cfg.project_root,
        "EnvironmentVariables": _mac_common_env(cfg),
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(Path.home() / "Library" / "Logs" / "local-ai-proxy-stack.log"),
        "StandardErrorPath": str(Path.home() / "Library" / "Logs" / "local-ai-proxy-stack.log"),
    }
    _write_macos_plist(plist_path, payload)
    _bootstrap_macos_plist(plist_path, APP_ID)
    return plist_path


def uninstall_macos() -> None:
    domain = f"gui/{os.getuid()}"
    for name in ("litellm", "gemini", "codex"):
        service_path = mac_service_plist_path(name)
        subprocess.run(["launchctl", "bootout", domain, str(service_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        service_path.unlink(missing_ok=True)
    plist_path = _mac_plist_path()
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    plist_path.unlink(missing_ok=True)


def install_linux() -> Path:
    cfg = load_config()
    path = _linux_desktop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    command = shlex.join(launch_command())
    content = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment=Local Codex, Gemini, and LiteLLM proxy stack
Exec={command}
Terminal=false
X-GNOME-Autostart-enabled=true
X-KDE-autostart-after=panel
"""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o644)
    _ = cfg
    return path


def uninstall_linux() -> None:
    _linux_desktop_path().unlink(missing_ok=True)


def install_windows() -> str:
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "LocalAIProxyStack", 0, winreg.REG_SZ, _windows_command())
    return key_path


def uninstall_windows() -> None:
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, "LocalAIProxyStack")
        except FileNotFoundError:
            pass


def install() -> str:
    system = platform.system()
    if system == "Darwin":
        return str(install_macos())
    if system == "Windows":
        return install_windows()
    return str(install_linux())


def uninstall() -> None:
    system = platform.system()
    if system == "Darwin":
        uninstall_macos()
    elif system == "Windows":
        uninstall_windows()
    else:
        uninstall_linux()


def is_installed() -> bool:
    system = platform.system()
    if system == "Darwin":
        return _mac_plist_path().exists()
    if system == "Windows":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, "LocalAIProxyStack")
            return True
        except Exception:
            return False
    return _linux_desktop_path().exists()
