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
    "com.yingfanqaq.local-ai-proxy-stack",
    "com.yingfanqaq.local-ai-proxy-stack.codex",
    "com.yingfanqaq.local-ai-proxy-stack.gemini",
    "com.yingfanqaq.local-ai-proxy-stack.litellm",
)


def launch_command(start_services: bool = True) -> list[str]:
    command = [sys.executable, "-m", "proxy_stack"]
    if start_services:
        command.append("start")
    else:
        command.append("status")
    return command


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"


def mac_service_label(name: str) -> str:
    return f"{APP_ID}.{name.replace('_', '-')}"


def mac_service_plist_path(name: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{mac_service_label(name)}.plist"


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


def _clean_env_value(value: object) -> str:
    text = str(value)
    return "".join(char for char in text if char == "\t" or char == "\n" or ord(char) >= 32)


def _mac_common_env(cfg) -> dict[str, str]:
    base = {
        **app_environment(cfg),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
    }
    return {key: _clean_env_value(value) for key, value in base.items()}


def _service_env_for_plist(env: dict[str, str]) -> dict[str, str]:
    allowed_prefixes = ("CODEX_", "GEMINI_", "CLAUDE_", "LITELLM_", "LOCAL_AI_PROXY")
    allowed_names = {"HOST", "PORT", "HOME", "PATH", "PYTHONUNBUFFERED", "PYTHON_BIN"}
    clean: dict[str, str] = {}
    for key, value in env.items():
        if key in allowed_names or key.startswith(allowed_prefixes):
            clean[key] = _clean_env_value(value)
    return clean


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
    from .manager import service_names, service_spec

    payloads: dict[str, tuple[Path, dict]] = {}
    common_env = _mac_common_env(cfg)
    for name in service_names(cfg):
        spec = service_spec(name, cfg)
        env = {**common_env, **_service_env_for_plist(spec.env)}
        label = mac_service_label(name)
        payloads[name] = (
            mac_service_plist_path(name),
            {
                "Label": label,
                "ProgramArguments": spec.command,
                "WorkingDirectory": str(spec.cwd),
                "EnvironmentVariables": env,
                "RunAtLoad": True,
                "KeepAlive": True,
                "StandardOutPath": str(spec.log_path),
                "StandardErrorPath": str(spec.log_path),
            },
        )
    return payloads


def install_macos() -> Path:
    remove_legacy_macos_agents()
    cfg = load_config()
    last_path = _mac_plist_path()
    for _name, (service_path, service_payload) in _mac_service_payloads(cfg).items():
        _write_macos_plist(service_path, service_payload)
        _bootstrap_macos_plist(service_path, service_payload["Label"])
        last_path = service_path
    _mac_plist_path().unlink(missing_ok=True)
    return last_path


def uninstall_macos() -> None:
    domain = f"gui/{os.getuid()}"
    agent_dir = Path.home() / "Library" / "LaunchAgents"
    for service_path in agent_dir.glob(f"{APP_ID}.*.plist"):
        subprocess.run(["launchctl", "bootout", domain, str(service_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        service_path.unlink(missing_ok=True)
    plist_path = _mac_plist_path()
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    plist_path.unlink(missing_ok=True)
    remove_legacy_macos_agents()


def install_linux() -> Path:
    cfg = load_config()
    path = _linux_desktop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    command = shlex.join(launch_command())
    content = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Comment=Local AI proxy flow manager
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
        winreg.SetValueEx(key, "proxyEverywhere", 0, winreg.REG_SZ, _windows_command())
    return key_path


def uninstall_windows() -> None:
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, "proxyEverywhere")
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
        agent_dir = Path.home() / "Library" / "LaunchAgents"
        return any(agent_dir.glob(f"{APP_ID}.*.plist"))
    if system == "Windows":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, "proxyEverywhere")
            return True
        except Exception:
            return False
    return _linux_desktop_path().exists()
