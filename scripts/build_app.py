from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEAVY_OPTIONAL_MODULES = [
    "IPython",
    "matplotlib",
    "pandas",
    "pytest",
    "scipy",
    "torch",
]


def build_python() -> str:
    venv_python = ROOT / ".venv" / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
    if venv_python.exists() and Path(sys.executable) != venv_python:
        return str(venv_python)
    return sys.executable


def pyinstaller_args() -> list[str]:
    sep = os.pathsep
    args = [
        "--name",
        "proxyEverywhere",
        "--windowed",
        "--osx-bundle-identifier",
        "com.yingfanqaq.proxyeverywhere",
        "--clean",
        "--noconfirm",
        "--collect-all",
        "litellm",
        "--collect-all",
        "fastapi",
        "--collect-all",
        "uvicorn",
        "--collect-all",
        "httpx",
        "--collect-all",
        "starlette",
        "--collect-all",
        "pydantic",
        "--collect-all",
        "pystray",
        "--collect-all",
        "PIL",
        "--hidden-import",
        "PySide6.QtCore",
        "--hidden-import",
        "PySide6.QtGui",
        "--hidden-import",
        "PySide6.QtWidgets",
        "--add-data",
        f"codex-chat-proxy{sep}codex-chat-proxy",
        "--add-data",
        f"gemini-genai-proxy{sep}gemini-genai-proxy",
        "--add-data",
        f"claude-code-proxy{sep}claude-code-proxy",
        "proxy_stack_app.py",
    ]
    for module in HEAVY_OPTIONAL_MODULES:
        args.extend(["--exclude-module", module])
    return args


def package_output() -> Path:
    system = platform.system().lower()
    machine = platform.machine().lower() or "unknown"
    dist = ROOT / "dist"
    name = f"proxyEverywhere-{system}-{machine}"
    if platform.system() == "Darwin":
        source = dist / "proxyEverywhere.app"
    elif platform.system() == "Windows":
        source = dist / "proxyEverywhere"
    else:
        source = dist / "proxyEverywhere"
    archive_base = dist / name
    archive = Path(shutil.make_archive(str(archive_base), "zip", root_dir=source.parent, base_dir=source.name))
    return archive


def finalize_macos_app() -> None:
    if platform.system() != "Darwin":
        return
    plist = ROOT / "dist" / "proxyEverywhere.app" / "Contents" / "Info.plist"
    if not plist.exists():
        return
    subprocess.run(
        ["/usr/libexec/PlistBuddy", "-c", "Set :LSUIElement true", str(plist)],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["/usr/libexec/PlistBuddy", "-c", "Add :LSUIElement bool true", str(plist)],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> None:
    subprocess.run([build_python(), "-m", "PyInstaller", *pyinstaller_args()], cwd=ROOT, check=True)
    finalize_macos_app()
    archive = package_output()
    print(archive)


if __name__ == "__main__":
    main()
