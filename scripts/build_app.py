from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def pyinstaller_args() -> list[str]:
    sep = os.pathsep
    args = [
        "--name",
        "LocalAIProxyStack",
        "--windowed",
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
        "--add-data",
        f"codex-chat-proxy{sep}codex-chat-proxy",
        "--add-data",
        f"gemini-genai-proxy{sep}gemini-genai-proxy",
        "proxy_stack_app.py",
    ]
    return args


def package_output() -> Path:
    system = platform.system().lower()
    machine = platform.machine().lower() or "unknown"
    dist = ROOT / "dist"
    name = f"LocalAIProxyStack-{system}-{machine}"
    if platform.system() == "Darwin":
        source = dist / "LocalAIProxyStack.app"
    elif platform.system() == "Windows":
        source = dist / "LocalAIProxyStack"
    else:
        source = dist / "LocalAIProxyStack"
    archive_base = dist / name
    archive = Path(shutil.make_archive(str(archive_base), "zip", root_dir=source.parent, base_dir=source.name))
    return archive


def main() -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", *pyinstaller_args()], cwd=ROOT, check=True)
    archive = package_output()
    print(archive)


if __name__ == "__main__":
    main()
